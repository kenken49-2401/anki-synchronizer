"""Read an open local Anki profile and upload a dashboard snapshot.

This connector never switches profiles, answers cards, or triggers AnkiWeb sync.
Anki Desktop and the AnkiConnect add-on must be running on the same computer.
"""

from __future__ import annotations

import argparse
from datetime import datetime, timezone as datetime_timezone
import ipaddress
import json
import os
from pathlib import Path
import sys
import tempfile
import time
from typing import Any
from urllib.parse import urlsplit, urlunsplit
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError
from card_media import rich, filename, raster, validate_media

import httpx


API_VERSION = 6
BATCH_SIZE = 100
MAX_CARDS = 50_000
MAX_REVIEWS = 1_000_000
MAX_RESPONSE_BYTES = 16 * 1024 * 1024
MAX_SNAPSHOT_BYTES = 32 * 1024 * 1024
MAX_ID = 2**53 - 1
REQUEST_TIMEOUT = httpx.Timeout(30, connect=5)


class ConnectorError(Exception):
    """A concise error that is safe to display without exposing card data."""


class UnsupportedAction(ConnectorError):
    pass


def _loopback(host: str | None) -> bool:
    if host == "localhost":
        return True
    try:
        return ipaddress.ip_address(host or "").is_loopback
    except ValueError:
        return False


def _validate_url(value: str, *, local_only: bool) -> str:
    try:
        parsed = urlsplit(value)
        # Accessing port validates its syntax and range.
        parsed.port
        valid = (
            parsed.scheme in {"http", "https"}
            and parsed.hostname
            and parsed.username is None
            and parsed.password is None
            and not parsed.query
            and not parsed.fragment
        )
        if not valid:
            raise ValueError
        if local_only and (not _loopback(parsed.hostname) or parsed.path not in {"", "/"}):
            raise ValueError
        if not local_only and parsed.scheme != "https" and not _loopback(parsed.hostname):
            raise ValueError
    except (ValueError, TypeError):
        if local_only:
            raise ConnectorError("AnkiConnect URL は http(s)://127.0.0.1:8765 等のローカル URL を指定してください。") from None
        raise ConnectorError("送信先には認証情報・クエリを含まない HTTPS URL を指定してください。") from None
    return value.rstrip("/")


def _bounded_json(response: httpx.Response, limit: int) -> Any:
    chunks: list[bytes] = []
    size = 0
    for chunk in response.iter_bytes():
        size += len(chunk)
        if size > limit:
            raise ConnectorError("応答が上限を超えました。--query で対象を絞ってください。")
        chunks.append(chunk)
    try:
        return json.loads(b"".join(chunks))
    except (ValueError, UnicodeError):
        raise ConnectorError("接続先から有効な JSON 応答を取得できませんでした。") from None


class AnkiConnect:
    def __init__(self, endpoint: str, api_key: str | None = None):
        self.endpoint = _validate_url(endpoint, local_only=True)
        self.api_key = api_key
        # Local Anki data and add-on credentials must never go to an HTTP proxy.
        self.client = httpx.Client(timeout=REQUEST_TIMEOUT, trust_env=False, follow_redirects=False)

    def __enter__(self) -> AnkiConnect:
        return self

    def __exit__(self, *_: Any) -> None:
        self.client.close()

    def call(self, action: str, **params: Any) -> Any:
        payload: dict[str, Any] = {"action": action, "version": API_VERSION, "params": params}
        if self.api_key:
            payload["key"] = self.api_key
        try:
            with self.client.stream("POST", self.endpoint, json=payload) as response:
                if response.status_code != 200:
                    raise ConnectorError(f"AnkiConnect が HTTP {response.status_code} を返しました。")
                result = _bounded_json(response, MAX_RESPONSE_BYTES)
        except httpx.HTTPError:
            raise ConnectorError("AnkiConnect に接続できません。Anki とアドオンを起動し、URL・API キーを確認してください。") from None
        if not isinstance(result, dict) or "result" not in result or "error" not in result:
            raise ConnectorError("AnkiConnect API v6 の応答形式が不正です。")
        if result["error"]:
            if result["error"] == "unsupported action":
                raise UnsupportedAction(f"AnkiConnect が {action} に対応していません。アドオンを更新してください。")
            # Remote errors can contain private fields or credentials. Do not echo them.
            raise ConnectorError(f"AnkiConnect の {action} に失敗しました。Anki の状態と API キーを確認してください。")
        return result["result"]

    def active_profile(self) -> str:
        try:
            name = self.call("getActiveProfile")
        except UnsupportedAction:
            profiles = self.call("getProfiles")
            if not isinstance(profiles, list) or len(profiles) != 1:
                raise ConnectorError(
                    "現在のプロファイルを確認できません。複数プロファイルでは getActiveProfile 対応の AnkiConnect が必要です。"
                ) from None
            name = profiles[0]
        if not isinstance(name, str) or not name.strip():
            raise ConnectorError("Anki のプロファイルを開いてから実行してください。")
        return name


def _integer(value: Any, label: str, *, minimum: int = -MAX_ID, maximum: int = MAX_ID) -> int:
    if type(value) is not int or value > maximum or value < minimum:
        raise ConnectorError(f"AnkiConnect の {label} が不正です。")
    return value


def _text(value: Any, label: str) -> str:
    if not isinstance(value, str):
        raise ConnectorError(f"AnkiConnect の {label} が不正です。")
    return value


def _fields(value: Any) -> dict[str, str]:
    if not isinstance(value, dict):
        raise ConnectorError("AnkiConnect のフィールド形式が不正です。")
    result: dict[str, str] = {}
    for key, field in value.items():
        if not isinstance(key, str) or not isinstance(field, dict):
            raise ConnectorError("AnkiConnect のフィールド形式が不正です。")
        result[key] = _text(field.get("value"), "フィールド値")
    return result


def _indexed_records(value: Any, key: str, expected: list[int]) -> dict[int, dict[str, Any]]:
    if not isinstance(value, list) or len(value) != len(expected):
        raise ConnectorError("取得中に Anki のカードが変わりました。学習や編集を止めて再実行してください。")
    records: dict[int, dict[str, Any]] = {}
    for record in value:
        if not isinstance(record, dict):
            raise ConnectorError("AnkiConnect のカード情報形式が不正です。")
        record_id = _integer(record.get(key), key, minimum=1)
        if record_id in records:
            raise ConnectorError("AnkiConnect のカード情報が重複しています。")
        records[record_id] = record
    if set(records) != set(expected):
        raise ConnectorError("取得中に Anki のカードが変わりました。学習や編集を止めて再実行してください。")
    return records


def export_snapshot(
    endpoint: str = "http://127.0.0.1:8765",
    api_key: str | None = None,
    expected_profile: str | None = None,
    timezone: str = "Asia/Tokyo",
    query: str = "",
    include_media: bool = True,
) -> dict[str, Any]:
    """Export card contents and complete review history using read-only API calls.

    The profile must already be open. With older add-ons lacking getActiveProfile,
    only a single-profile Anki installation can be identified safely.
    """
    try:
        ZoneInfo(timezone)
    except (ZoneInfoNotFoundError, ValueError):
        raise ConnectorError("有効なタイムゾーン（例: Asia/Tokyo）を指定してください。") from None
    cards: list[dict[str, Any]] = []
    reviews: list[dict[str, Any]] = []
    review_ids: set[int] = set()
    media = {}
    with AnkiConnect(endpoint, api_key) as anki:
        profile = anki.active_profile()
        if expected_profile is not None and profile != expected_profile:
            raise ConnectorError("指定したプロファイルと Anki で開いているプロファイルが異なります。送信を中止しました。")
        card_ids = anki.call("findCards", query=query)
        if not isinstance(card_ids, list):
            raise ConnectorError("AnkiConnect のカード一覧形式が不正です。")
        if len(card_ids) > MAX_CARDS:
            raise ConnectorError(f"カード数が上限 {MAX_CARDS:,} 件を超えました。--query で対象を絞ってください。")
        card_ids = [_integer(card_id, "カード ID", minimum=1) for card_id in card_ids]
        if len(set(card_ids)) != len(card_ids):
            raise ConnectorError("AnkiConnect のカード ID が重複しています。")
        for offset in range(0, len(card_ids), BATCH_SIZE):
            batch = card_ids[offset : offset + BATCH_SIZE]
            info = _indexed_records(anki.call("cardsInfo", cards=batch), "cardId", batch)
            note_ids = list(dict.fromkeys(_integer(info[cid].get("note"), "ノート ID", minimum=1) for cid in batch))
            notes = _indexed_records(anki.call("notesInfo", notes=note_ids), "noteId", note_ids)
            history = anki.call("getReviewsOfCards", cards=batch)
            if not isinstance(history, dict) or set(history) != {str(cid) for cid in batch}:
                raise ConnectorError("AnkiConnect の学習履歴形式が不正です。")
            for card_id in batch:
                card = info[card_id]
                note_id = card["note"]
                note = notes[note_id]
                tags = note.get("tags")
                if not isinstance(tags, list) or any(not isinstance(tag, str) for tag in tags):
                    raise ConnectorError("AnkiConnect のタグ形式が不正です。")
                cards.append({
                    "id": card_id,
                    "note_id": note_id,
                    "deck": _text(card.get("deckName"), "デッキ名"),
                    "model": _text(card.get("modelName"), "ノートタイプ"),
                    "tags": sorted(set(tags)),
                    "front": _text(card.get("question"), "カード表面"),
                    "back": _text(card.get("answer"), "カード裏面"),
                    "fields": _fields(note.get("fields")),
                    "reps": _integer(card.get("reps"), "学習回数", minimum=0),
                    "lapses": _integer(card.get("lapses"), "忘却回数", minimum=0),
                    "interval": _integer(card.get("interval"), "学習間隔"),
                    "due": _integer(card.get("due"), "学習期限"),
                    "suspended": _integer(card.get("queue"), "キュー") == -1,
                })
                cards[-1]["queue"] = _integer(card.get("queue"), "キュー")
                cards[-1]["added_at"] = card_id
                for remote, local in (("type", "type"), ("factor", "ease_factor")):
                    if remote in card:
                        cards[-1][local] = _integer(card[remote], local)
                card_reviews = history[str(card_id)]
                if not isinstance(card_reviews, list):
                    raise ConnectorError("AnkiConnect の学習履歴形式が不正です。")
                if len(reviews) + len(card_reviews) > MAX_REVIEWS:
                    raise ConnectorError("学習履歴が上限を超えました。--query で対象を絞ってください。")
                for review in card_reviews:
                    if not isinstance(review, dict):
                        raise ConnectorError("AnkiConnect の学習履歴形式が不正です。")
                    review_id = _integer(review.get("id"), "学習履歴 ID", minimum=1)
                    if review_id in review_ids:
                        raise ConnectorError("AnkiConnect の学習履歴 ID が重複しています。")
                    review_ids.add(review_id)
                    reviews.append({
                        "id": review_id,
                        "card_id": card_id,
                        "ease": _integer(review.get("ease"), "回答評価", minimum=0, maximum=4),
                        "time_ms": _integer(review.get("time"), "学習時間", minimum=0),
                        "type": _integer(review.get("type"), "学習種別", minimum=0, maximum=5),
                    })
                    for remote, local in (("ivl", "interval"), ("lastIvl", "last_interval"), ("factor", "ease_factor")):
                        if remote in review:
                            reviews[-1][local] = _integer(review[remote], local)
        if include_media:
            names = set()
            for card in cards:
                for side in ("front", "back"):
                    _, refs = rich(card[side])
                    names.update(refs)
            if len(names) > 500:
                raise ConnectorError("画像数が500件を超えました。--query または --no-media を使ってください。")
            import base64
            for name in sorted(names):
                if filename(name) != name:
                    continue
                encoded = anki.call("retrieveMediaFile", filename=name)
                if encoded is False or encoded is None:
                    continue
                try:
                    if not isinstance(encoded, str) or len(encoded) > 2796204:
                        raise ValueError()
                    data = base64.b64decode(encoded, validate=True)
                    mime = raster(data)
                    if not mime:
                        continue
                    media[name] = {"mime": mime, "data": encoded}
                    validate_media(media)
                except ValueError:
                    raise ConnectorError("画像の形式または容量が制限を超えています。--no-media も利用できます。") from None
        if anki.active_profile() != profile:
            raise ConnectorError("取得中に Anki のプロファイルが変わりました。送信を中止しました。")
    snapshot = {
        "schema_version": 1,
        "source": {"profile": profile, "kind": "ankiconnect", "timezone": timezone},
        "synced_at": datetime.now(datetime_timezone.utc).isoformat(),
        "cards": cards,
        "reviews": sorted(reviews, key=lambda review: review["id"]),
    }
    if media:
        snapshot["media"] = media
    _encode_snapshot(snapshot)
    return snapshot


def _encode_snapshot(snapshot: dict[str, Any]) -> bytes:
    encoded = json.dumps(snapshot, ensure_ascii=False, separators=(",", ":"), allow_nan=False).encode("utf-8")
    if len(encoded) > MAX_SNAPSHOT_BYTES:
        raise ConnectorError("スナップショットが 32 MiB を超えました。--query で対象を絞ってください。")
    return encoded


def upload_snapshot(server: str, token: str, snapshot: dict[str, Any]) -> None:
    """Send a snapshot to the owner's HTTPS dashboard without following redirects."""
    base = _validate_url(server, local_only=False)
    parsed = urlsplit(base)
    path = parsed.path.rstrip("/")
    if not path.endswith("/api/snapshot"):
        path += "/api/snapshot"
    endpoint = urlunsplit((parsed.scheme, parsed.netloc, path, "", ""))
    if not token or any(not 33 <= ord(character) <= 126 for character in token):
        raise ConnectorError("送信用トークンが未設定または不正です。環境変数に設定してください。")
    try:
        # Keep the platform/user's trusted proxy and CA configuration for HTTPS.
        with httpx.Client(timeout=REQUEST_TIMEOUT, follow_redirects=False, trust_env=not _loopback(parsed.hostname)) as client:
            with client.stream(
                "POST", endpoint, content=_encode_snapshot(snapshot),
                headers={"Authorization": f"Bearer {token}", "Content-Type": "application/json"},
            ) as response:
                if not 200 <= response.status_code < 300:
                    raise ConnectorError(f"ダッシュボードへの送信が HTTP {response.status_code} で失敗しました。URL とトークンを確認してください。")
    except httpx.HTTPError:
        raise ConnectorError("ダッシュボードに接続できません。URL・ネットワーク・TLS 設定を確認してください。") from None


def save_snapshot(path: str | Path, snapshot: dict[str, Any]) -> None:
    """Atomically save private card data with owner-only file permissions."""
    target = Path(path)
    temporary: str | None = None
    try:
        with tempfile.NamedTemporaryFile(dir=target.parent, prefix=f".{target.name}.", delete=False) as handle:
            temporary = handle.name
            handle.write(_encode_snapshot(snapshot))
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, target)
        temporary = None
    except OSError:
        raise ConnectorError("スナップショットを保存できません。保存先の権限と空き容量を確認してください。") from None
    finally:
        if temporary is not None:
            try:
                os.unlink(temporary)
            except OSError:
                pass


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="AnkiConnect のカードと学習履歴をダッシュボードへ送信します。")
    parser.add_argument("--server", help="ダッシュボードの HTTPS URL")
    parser.add_argument("--token-env", default="ANKI_UPLOAD_TOKEN", help="送信用トークンを格納した環境変数名")
    parser.add_argument("--anki-url", default="http://127.0.0.1:8765")
    parser.add_argument("--api-key-env", default="ANKI_CONNECT_API_KEY", help="AnkiConnect API キーの環境変数名")
    parser.add_argument("--profile", help="Anki で既に開いているプロファイル名（不一致なら停止）")
    parser.add_argument("--timezone", default="Asia/Tokyo")
    parser.add_argument("--query", default="", help="Anki の検索条件（空文字は全カード）")
    parser.add_argument("--no-media", action="store_true", help="画像を取得しない")
    parser.add_argument("--watch", type=int, metavar="SECONDS", help="指定秒数ごとに繰り返す（最小 30 秒）")
    parser.add_argument("--output", help="送信に加えて、または送信せずに JSON をローカル保存")
    args = parser.parse_args(argv)
    if not args.server and not args.output:
        parser.error("--server または --output を指定してください。")
    if args.watch is not None and args.watch < 30:
        parser.error("--watch は 30 秒以上を指定してください。")
    try:
        if args.server:
            _validate_url(args.server, local_only=False)
            if not os.environ.get(args.token_env):
                raise ConnectorError(f"環境変数 {args.token_env} に送信用トークンを設定してください。")
        _validate_url(args.anki_url, local_only=True)
        while True:
            try:
                snapshot = export_snapshot(
                    endpoint=args.anki_url,
                    api_key=os.environ.get(args.api_key_env),
                    expected_profile=args.profile,
                    timezone=args.timezone,
                    query=args.query,
                    include_media=not args.no_media,
                )
                if args.output:
                    save_snapshot(args.output, snapshot)
                if args.server:
                    upload_snapshot(args.server, os.environ.get(args.token_env, ""), snapshot)
                print(f"完了: カード {len(snapshot['cards']):,} 件 / 学習履歴 {len(snapshot['reviews']):,} 件", flush=True)
            except ConnectorError as exc:
                if args.watch is None:
                    raise
                print(f"同期待機: {exc}", file=sys.stderr, flush=True)
            if args.watch is None:
                return 0
            time.sleep(args.watch)
    except ConnectorError as exc:
        print(f"エラー: {exc}", file=sys.stderr)
        return 1
    except KeyboardInterrupt:
        return 0


if __name__ == "__main__":
    raise SystemExit(main())
