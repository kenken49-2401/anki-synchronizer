"""Download AnkiWeb into a disposable collection and refresh the dashboard.

Only the official full-download operation is used. Normal collection sync and
media sync are deliberately absent: both can send local changes to AnkiWeb.
Credentials come from environment variables and are never written to disk.
"""

from __future__ import annotations

import argparse
from datetime import datetime, timezone as datetime_timezone
from pathlib import Path
import os
import re
import sys
import tempfile
from typing import Any
from urllib.parse import urlsplit
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from anki import sync_pb2
from anki.collection import Collection

from connector import (
    BATCH_SIZE, MAX_CARDS, MAX_ID, MAX_REVIEWS, ConnectorError,
    _encode_snapshot, _loopback, _validate_url, upload_snapshot,
)


DEFAULT_ENDPOINT = "https://sync.ankiweb.net/"
MAX_COLLECTION_BYTES = 256 * 1024 * 1024


class CloudSyncError(ConnectorError):
    """A safe, fixed diagnostic containing no credentials or collection data."""


def _validate_endpoint(endpoint: str, *, test_local_only: bool = False) -> str:
    """Constrain token destinations; the local-server override is not a CLI flag."""
    try:
        parsed = urlsplit(endpoint)
        port = parsed.port
        valid = (
            bool(parsed.hostname)
            and parsed.username is None and parsed.password is None
            and not parsed.query and not parsed.fragment
            and parsed.path in {"", "/"}
        )
        if test_local_only:
            valid = valid and parsed.scheme in {"http", "https"} and _loopback(parsed.hostname)
        else:
            valid = (
                valid and parsed.scheme == "https" and port in {None, 443}
                and re.fullmatch(r"[a-z0-9-]+(?:\.[a-z0-9-]+)*\.ankiweb\.net", parsed.hostname or "") is not None
            )
        if not valid:
            raise ValueError
    except (TypeError, ValueError):
        raise CloudSyncError("AnkiWeb endpoint must be an HTTPS ankiweb.net subdomain URL.") from None
    return endpoint.rstrip("/") + "/"


def _int(value: Any, *, minimum: int = -MAX_ID, maximum: int = MAX_ID) -> int:
    if type(value) is not int or not minimum <= value <= maximum:
        raise CloudSyncError("Downloaded collection contains unsupported numeric values.")
    return value


def _extract_snapshot(col: Collection, *, timezone: str, query: str, allow_empty: bool) -> dict[str, Any]:
    card_ids = col.find_cards(query)
    if not card_ids and not allow_empty:
        raise CloudSyncError("No cards were downloaded or matched the query; existing dashboard data was preserved. Use --allow-empty only deliberately.")
    if len(card_ids) > MAX_CARDS:
        raise CloudSyncError("Card count exceeds the dashboard limit; narrow --query.")
    cards: list[dict[str, Any]] = []
    reviews: list[dict[str, Any]] = []
    for offset in range(0, len(card_ids), BATCH_SIZE):
        batch = card_ids[offset:offset + BATCH_SIZE]
        for cid in batch:
            card = col.get_card(cid)
            note = card.note()
            model = note.note_type()
            deck = col.decks.get(card.odid or card.did)
            if model is None or deck is None:
                raise CloudSyncError("Downloaded collection contains missing note types or decks.")
            rendered = card.render_output()
            cards.append({
                "id": _int(int(card.id), minimum=1),
                "note_id": _int(int(note.id), minimum=1),
                "deck": deck["name"], "model": model["name"],
                "tags": sorted(set(note.tags)),
                "front": rendered.question_text, "back": rendered.answer_text,
                "fields": dict(note.items()),
                "reps": _int(card.reps, minimum=0),
                "lapses": _int(card.lapses, minimum=0),
                "interval": _int(card.ivl), "due": _int(card.due),
                "suspended": card.queue == -1,
            })
        # Fetch one past the remaining allowance, so limits always fail closed.
        placeholders = ",".join("?" for _ in batch)
        rows = col.db.all(
            f"select id, cid, ease, time, type from revlog where cid in ({placeholders}) order by id limit ?",
            *batch, MAX_REVIEWS - len(reviews) + 1,
        )
        if len(reviews) + len(rows) > MAX_REVIEWS:
            raise CloudSyncError("Review count exceeds the dashboard limit; narrow --query.")
        for rid, cid, ease, duration, kind in rows:
            reviews.append({
                "id": _int(rid, minimum=1), "card_id": _int(cid, minimum=1),
                "ease": _int(ease, minimum=0, maximum=4),
                "time_ms": _int(duration, minimum=0), "type": _int(kind, minimum=0, maximum=5),
            })
    snapshot = {
        "schema_version": 1,
        "source": {"kind": "ankiweb", "profile": "AnkiWeb", "timezone": timezone},
        "synced_at": datetime.now(datetime_timezone.utc).isoformat(),
        "cards": cards, "reviews": sorted(reviews, key=lambda review: review["id"]),
    }
    _encode_snapshot(snapshot)
    return snapshot



def resolve_download_endpoint(col: Collection, auth: sync_pb2.SyncAuth, *, test_local_only: bool = False) -> None:
    """Read server metadata first, as Anki does, to discover the account's shard.

    Login provides a token, not the collection server. A direct full download
    from the login server can return a non-sync response (missing original size).
    sync_status only reads metadata; it never sends cards, reviews or media.
    """
    status = col.sync_status(auth)
    if status.new_endpoint:
        auth.endpoint = _validate_endpoint(status.new_endpoint, test_local_only=test_local_only)


def export_snapshot(
    hkey: str,
    endpoint: str | None = None,
    *,
    timezone: str = "Asia/Tokyo",
    query: str = "",
    allow_empty: bool = False,
    _test_endpoint: str | None = None,
) -> dict[str, Any]:
    """Read AnkiWeb using a fresh isolated collection, then delete all local data.

    ``_test_endpoint`` is restricted to loopback, for the official local sync
    server in integration tests. Production callers and CLI use ``endpoint``.
    No media API is invoked, because the supported media sync is bidirectional.
    """
    if not isinstance(hkey, str) or not hkey or len(hkey) > 4096 or any(not 33 <= ord(char) <= 126 for char in hkey):
        raise CloudSyncError("Set ANKIWEB_HKEY to an AnkiWeb sync token.")
    selected_endpoint = _validate_endpoint(
        _test_endpoint if _test_endpoint is not None else endpoint or DEFAULT_ENDPOINT,
        test_local_only=_test_endpoint is not None,
    )
    try:
        ZoneInfo(timezone)
    except (ZoneInfoNotFoundError, ValueError, TypeError):
        raise CloudSyncError("Set a valid timezone, for example Asia/Tokyo.") from None
    try:
        with tempfile.TemporaryDirectory(prefix="anki-dashboard-") as directory:
            col: Collection | None = None
            try:
                path = Path(directory) / "collection.anki2"
                col = Collection(str(path))
                auth = sync_pb2.SyncAuth(hkey=hkey, endpoint=selected_endpoint, io_timeout_secs=60)
                resolve_download_endpoint(col, auth, test_local_only=_test_endpoint is not None)
                col.close_for_full_sync()
                # Never call sync_collection: even normal sync can upload edits.
                col._backend.full_upload_or_download(sync_pb2.FullUploadOrDownloadRequest(auth=auth, upload=False))
                col.reopen(after_full_sync=True)
                if path.stat().st_size > MAX_COLLECTION_BYTES:
                    raise CloudSyncError("Downloaded collection exceeds the 256 MiB limit.")
                return _extract_snapshot(col, timezone=timezone, query=query, allow_empty=allow_empty)
            finally:
                if col is not None:
                    try:
                        col.close()
                    finally:
                        # Failed download/reopen can leave db=None while the Rust
                        # backend still owns a file handle. Explicitly release it.
                        try:
                            col._backend.close_collection(downgrade_to_schema11=False)
                        except Exception:
                            pass
    except ConnectorError:
        raise
    except Exception:
        # Anki/network exceptions may contain URLs, tokens, or card contents.
        raise CloudSyncError("AnkiWeb download failed. Check the sync token, endpoint, network and collection compatibility; no dashboard update was sent.") from None


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Read AnkiWeb and update the dashboard without a running PC.")
    parser.add_argument("--timezone", default=os.environ.get("ANKI_TIMEZONE", "Asia/Tokyo"))
    parser.add_argument("--query", default="", help="Anki search query (default: all cards)")
    parser.add_argument("--allow-empty", action="store_true", help="Deliberately permit replacing the dashboard with zero cards")
    args = parser.parse_args(argv)
    try:
        server = os.environ.get("DASHBOARD_URL", "")
        token = os.environ.get("ANKI_UPLOAD_TOKEN", "")
        if not server or not token:
            raise CloudSyncError("Set DASHBOARD_URL and ANKI_UPLOAD_TOKEN in the environment.")
        _validate_url(server, local_only=False)
        if urlsplit(server).scheme != "https":
            raise CloudSyncError("DASHBOARD_URL must use HTTPS.")
        if any(not 33 <= ord(char) <= 126 for char in token):
            raise CloudSyncError("ANKI_UPLOAD_TOKEN contains unsupported characters.")
        snapshot = export_snapshot(
            os.environ.get("ANKIWEB_HKEY", ""), os.environ.get("ANKIWEB_ENDPOINT") or None,
            timezone=args.timezone, query=args.query, allow_empty=args.allow_empty,
        )
        upload_snapshot(server, token, snapshot)
        print(f"Dashboard updated: {len(snapshot['cards']):,} cards, {len(snapshot['reviews']):,} reviews.")
        return 0
    except ConnectorError as exc:
        print(f"Cloud sync failed: {exc}", file=sys.stderr)
        return 1
    except Exception:
        print("Cloud sync failed; credentials and card data were not logged.", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
