"""Use Anki's real scheduler; persist the entire transaction before returning success."""
from __future__ import annotations

import base64
import hashlib
import html
import io
import json
import re
import tempfile
import threading
import time
import uuid
import zipfile
from html.parser import HTMLParser
from pathlib import Path
from typing import Callable, Any

from anki.collection import Collection
from anki.cards import Card
from anki import scheduler_pb2, sync_pb2
from cryptography.fernet import Fernet, InvalidToken
from fastmcp.exceptions import ToolError

from storage import StorageError


class UserError(ToolError):
    pass


class TextParser(HTMLParser):
    def __init__(self):
        super().__init__()
        self.parts: list[str] = []
        self.hidden = 0

    def handle_starttag(self, tag, attrs):
        if tag in ("script", "style"):
            self.hidden += 1
        if tag in ("br", "p", "div", "hr", "li") and not self.hidden:
            self.parts.append("\n")

    def handle_endtag(self, tag):
        if tag in ("script", "style") and self.hidden:
            self.hidden -= 1

    def handle_data(self, data):
        if not self.hidden:
            self.parts.append(data)


def plain(value: str) -> str:
    parser = TextParser()
    parser.feed(value)
    return re.sub(r"\n{3,}", "\n\n", "".join(parser.parts)).strip()


def digest(value: Any) -> str:
    return hashlib.sha256(json.dumps(value, sort_keys=True, ensure_ascii=False).encode()).hexdigest()


def valid_request_id(request_id: str) -> None:
    try:
        uuid.UUID(request_id)
    except (ValueError, AttributeError):
        raise UserError("request_idには新しいUUIDを使ってください。同じ操作の再送には同じUUIDを使います。") from None


class Engine:
    def __init__(self, db, encryption_key: str, *, max_bytes: int = 20 * 1024 * 1024,
                 ankiweb_hkey: str = "", ankiweb_endpoint: str = ""):
        self.db = db
        self.cipher = Fernet(encryption_key.encode())
        self.max_bytes = max_bytes
        self.hkey = ankiweb_hkey
        self.endpoint = ankiweb_endpoint
        self.lock = threading.Lock()

    def _restore(self, payload: str | None, root: Path) -> dict:
        if payload is None:
            return {"requests": {}, "review": None, "last_sync": None}
        # Bound authenticated archive size both before decryption and decompression.
        if len(payload) > self.max_bytes * 2 + 4096:
            raise UserError("保存データがサイズ上限を超えています。")
        try:
            raw = self.cipher.decrypt(payload.encode())
        except InvalidToken:
            raise UserError("保存データを復号できません。暗号化キーを確認してください。空のデータでは上書きしません。") from None
        with zipfile.ZipFile(io.BytesIO(raw)) as archive:
            infos = archive.infolist()
            if {i.filename for i in infos} != {"collection.anki2", "state.json"} or len(infos) != 2:
                raise UserError("保存データの形式が不正です。")
            if sum(i.file_size for i in infos) > self.max_bytes:
                raise UserError("展開後のデータがサイズ上限を超えています。")
            for info in infos:
                (root / info.filename).write_bytes(archive.read(info))
        return json.loads((root / "state.json").read_text())

    def _snapshot(self, root: Path, state: dict) -> str:
        metadata = json.dumps(state, ensure_ascii=False).encode()
        path = root / "collection.anki2"
        if path.stat().st_size + len(metadata) > self.max_bytes:
            raise UserError("無料枠保護のため、コレクション上限20MBを超える操作を停止しました。")
        output = io.BytesIO()
        with zipfile.ZipFile(output, "w", compression=zipfile.ZIP_DEFLATED) as archive:
            archive.write(path, "collection.anki2")
            archive.writestr("state.json", metadata)
        return self.cipher.encrypt(output.getvalue()).decode()

    def run(self, action: Callable[[Collection, dict], Any], *, request_id: str | None = None,
            fingerprint: dict | None = None) -> Any:
        if request_id:
            valid_request_id(request_id)
        with self.lock:
            lease = str(uuid.uuid4())
            remote = self.db.acquire(lease)  # Never fall back to an empty collection on failure.
            try:
                with tempfile.TemporaryDirectory(prefix="anki-mcp-") as directory:
                    root = Path(directory)
                    state = self._restore(remote["payload"], root)
                    fp = digest(fingerprint)
                    if request_id and request_id in state["requests"]:
                        previous = state["requests"][request_id]
                        if previous["fingerprint"] != fp:
                            raise UserError("同じrequest_idが異なる操作に使われています。")
                        return previous["result"]
                    col = Collection(str(root / "collection.anki2"))
                    try:
                        result = action(col, state)
                    finally:
                        col.close()
                    if request_id:
                        state["requests"][request_id] = {"fingerprint": fp, "result": result}
                    payload = self._snapshot(root, state)
                    self.db.commit(lease, remote["revision"], payload)
                    return result
            finally:
                try:
                    self.db.release(lease)
                except StorageError:
                    pass  # Expiring lease handles interruption; never mask a failed commit.

    @staticmethod
    def note_info(col: Collection, note_id: int) -> dict:
        note = col.get_note(note_id)
        raw = {"fields": dict(note.items()), "tags": note.tags, "model": note.mid}
        return {"note_id": note.id, "version": digest(raw), "note_type": note.note_type()["name"],
                "fields": {k: plain(v) for k, v in note.items()}, "tags": note.tags,
                "card_ids": [int(c) for c in note.card_ids()]}

    def describe(self) -> dict:
        def action(col, state):
            return {"decks": [{"id": d.id, "name": d.name} for d in col.decks.all_names_and_ids()],
                    "note_types": [{"name": m["name"], "fields": [f["name"] for f in m["flds"]]}
                                   for m in col.models.all()],
                    "cards": col.card_count(), "last_sync": state["last_sync"],
                    "ankiweb_configured": bool(self.hkey), "media_supported": False,
                    "snapshot_limit_bytes": self.max_bytes}
        return self.run(action)

    def search(self, query: str, limit: int = 20, offset: int = 0) -> dict:
        if not 1 <= limit <= 50 or not 0 <= offset <= 10000 or len(query) > 1000:
            raise UserError("検索範囲または検索文字列が上限を超えています。")
        def action(col, state):
            ids = col.find_notes(query)
            return {"total": len(ids), "notes": [self.note_info(col, n) for n in ids[offset:offset + limit]]}
        return self.run(action)

    def add(self, deck: str, note_type: str, fields: dict[str, str], tags: list[str], request_id: str) -> dict:
        def action(col, state):
            model = col.models.by_name(note_type)
            if model is None:
                raise UserError("指定したノートタイプがありません。describe_collectionで確認してください。")
            note = col.new_note(model)
            self._apply_fields(note, fields)
            if not plain(note.fields[0]):
                raise UserError("先頭フィールドは空にできません。")
            if note.fields_check():
                raise UserError("先頭フィールドが重複しています。既存カードを検索してください。")
            note.tags = self._tags(tags)
            if not deck or len(deck) > 150:
                raise UserError("デッキ名が不正です。")
            col.add_note(note, col.decks.id(deck))
            state["review"] = None
            return self.note_info(col, note.id)
        return self.run(action, request_id=request_id, fingerprint={"op": "add", "deck": deck,
                        "type": note_type, "fields": fields, "tags": tags})

    @staticmethod
    def _apply_fields(note, fields: dict[str, str]) -> None:
        if not fields or set(fields) - set(note.keys()):
            raise UserError("フィールド名がノートタイプと一致しません。")
        if any(not isinstance(v, str) or len(v) > 20000 for v in fields.values()):
            raise UserError("各フィールドは20,000文字以内の文字列にしてください。")
        for key, value in fields.items():
            note[key] = html.escape(value).replace("\n", "<br>")

    @staticmethod
    def _tags(tags: list[str]) -> list[str]:
        if len(tags) > 50 or any(not t or len(t) > 100 or re.search(r"\s", t) for t in tags):
            raise UserError("タグは空白なし・100文字以内、最大50個にしてください。")
        return list(dict.fromkeys(tags))

    def edit(self, note_id: int, version: str, fields: dict[str, str], tags: list[str] | None, request_id: str) -> dict:
        def action(col, state):
            if self.note_info(col, note_id)["version"] != version:
                raise UserError("ノートが変更されています。検索し直してから編集してください。")
            note = col.get_note(note_id)
            self._apply_fields(note, fields)
            if not plain(note.fields[0]):
                raise UserError("先頭フィールドは空にできません。")
            if tags is not None:
                note.tags = self._tags(tags)
            col.update_note(note)
            state["review"] = None
            return self.note_info(col, note_id)
        return self.run(action, request_id=request_id, fingerprint={"op": "edit", "id": note_id,
                        "version": version, "fields": fields, "tags": tags})

    def delete(self, note_id: int, version: str, request_id: str) -> dict:
        def action(col, state):
            if self.note_info(col, note_id)["version"] != version:
                raise UserError("ノートが変更されています。検索し直してください。")
            col.remove_notes([note_id])
            state["review"] = None
            return {"deleted_note_id": note_id}
        return self.run(action, request_id=request_id, fingerprint={"op": "delete", "id": note_id, "version": version})

    @staticmethod
    def _review_card(col, state, token: str):
        review = state["review"]
        if not review or review["token"] != token:
            raise UserError("復習セッションがありません。next_reviewからやり直してください。")
        if time.time() - review["shown_at"] > 3600:
            raise UserError("復習セッションの期限が切れています。")
        card = col.get_card(review["card_id"])
        current = col._backend.get_scheduling_states(card.id)
        if base64.b64encode(current.current.SerializeToString()).decode() != review["current_state"]:
            raise UserError("カードの復習状態が変更されています。next_reviewからやり直してください。")
        if Engine.note_info(col, card.nid)["version"] != review["note_version"]:
            raise UserError("カード内容が変更されています。next_reviewからやり直してください。")
        return card, current, review

    def next_review(self, deck: str, request_id: str) -> dict:
        def action(col, state):
            deck_obj = col.decks.by_name(deck)
            if deck_obj is None:
                raise UserError("指定したデッキがありません。")
            col.decks.select(deck_obj["id"])
            queued = col.sched.get_queued_cards(fetch_limit=1)
            counts = {"new": queued.new_count, "learning": queued.learning_count, "review": queued.review_count}
            if not queued.cards:
                state["review"] = None
                return {"finished": True, "counts": counts}
            item = queued.cards[0]
            card = Card(col, backend_card=item.card)
            token = str(uuid.uuid4())
            state["review"] = {"token": token, "card_id": int(card.id), "shown_at": time.time(),
                               "revealed": False, "note_version": self.note_info(col, card.nid)["version"],
                               "current_state": base64.b64encode(item.states.current.SerializeToString()).decode()}
            return {"finished": False, "review_token": token, "card_id": int(card.id),
                    "question": plain(card.question()), "counts": counts}
        return self.run(action, request_id=request_id, fingerprint={"op": "next", "deck": deck})

    def reveal(self, token: str) -> dict:
        def action(col, state):
            card, states, review = self._review_card(col, state, token)
            review["revealed"] = True
            return {"card_id": int(card.id), "answer": plain(card.answer()),
                    "ratings": dict(zip(["again", "hard", "good", "easy"], col.sched.describe_next_states(states)))}
        return self.run(action)

    def answer(self, token: str, rating: str, request_id: str) -> dict:
        ratings = {"again": scheduler_pb2.CardAnswer.AGAIN, "hard": scheduler_pb2.CardAnswer.HARD,
                   "good": scheduler_pb2.CardAnswer.GOOD, "easy": scheduler_pb2.CardAnswer.EASY}
        if rating not in ratings:
            raise UserError("評価はagain/hard/good/easyのいずれかです。")
        def action(col, state):
            card, states, review = self._review_card(col, state, token)
            if not review["revealed"]:
                raise UserError("先にreveal_answerで答えを表示してください。")
            card.start_timer()
            answer = col.sched.build_answer(card=card, states=states, rating=ratings[rating])
            answer.milliseconds_taken = min(int((time.time() - review["shown_at"]) * 1000), card.time_limit())
            col.sched.answer_card(answer)
            state["review"] = None
            card.load()
            return {"recorded": True, "card_id": int(card.id), "rating": rating,
                    "repetitions": card.reps, "interval_days": card.ivl}
        return self.run(action, request_id=request_id, fingerprint={"op": "answer", "token": token, "rating": rating})

    def sync(self, request_id: str, direction: str = "normal", confirmation: str = "") -> dict:
        if not self.hkey:
            raise UserError("AnkiWebの同期トークンをRenderの環境変数に設定してください。")
        if direction not in ("normal", "download", "upload"):
            raise UserError("同期方向が不正です。")
        if direction != "normal" and confirmation != "REPLACE COLLECTION":
            raise UserError("全体置換にはユーザーの明示指示とconfirmation='REPLACE COLLECTION'が必要です。")
        def action(col, state):
            auth = sync_pb2.SyncAuth(hkey=self.hkey, io_timeout_secs=30)
            if self.endpoint:
                auth.endpoint = self.endpoint
            result = col.sync_collection(auth, sync_media=False)
            if result.new_endpoint:
                auth.endpoint = result.new_endpoint
            required = result.required
            if required in (result.FULL_SYNC, result.FULL_DOWNLOAD, result.FULL_UPLOAD):
                # A fresh, empty local collection can only download; never guess a destructive direction.
                selected = direction
                if direction == "normal" and required == result.FULL_DOWNLOAD and col.card_count() == 0:
                    selected = "download"
                if selected == "normal":
                    return {"synced": False, "full_sync_required": True, "required": int(required),
                            "message": "全体同期が必要です。保存済みデータは維持しています。置換方向を明示してください。"}
                if selected == "upload" and required == result.FULL_DOWNLOAD:
                    raise UserError("空のローカルデータでAnkiWebを置換する操作は拒否しました。")
                if selected == "download" and required == result.FULL_UPLOAD:
                    raise UserError("空のAnkiWebデータでローカルを置換する操作は拒否しました。")
                col.close_for_full_sync()
                try:
                    col._backend.full_upload_or_download(sync_pb2.FullUploadOrDownloadRequest(
                        auth=auth, upload=selected == "upload"))
                finally:
                    col.reopen(after_full_sync=True)
            state["review"] = None
            state["last_sync"] = int(time.time())
            return {"synced": True, "cards": col.card_count(), "media_synced": False}
        return self.run(action, request_id=request_id, fingerprint={"op": "sync", "direction": direction, "confirmation": confirmation})
