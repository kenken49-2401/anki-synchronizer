"""Private, single-owner Anki dashboard and encrypted snapshot API.

Run ``uvicorn dashboard:app`` after configuring the three required secrets.
The module does not load Anki or open the collection; a local connector uploads
read-only snapshots.  ``create_dashboard`` accepts explicit configuration for
tests and embedding, while the ASGI entry point validates the environment on
startup and refuses to start with missing or weak secrets.
"""

from __future__ import annotations

import base64
from collections import defaultdict, deque
from dataclasses import dataclass
from datetime import datetime, timezone
import hashlib
import hmac
from html.parser import HTMLParser
import json
import math
import os
from pathlib import Path
import re
import secrets
import tempfile
import time
from typing import Any
from urllib.parse import urlsplit
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from cryptography.fernet import Fernet, InvalidToken
from starlette.applications import Starlette
from starlette.concurrency import run_in_threadpool
from starlette.exceptions import HTTPException
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import JSONResponse, Response
from card_media import validate_media, rich
from note_identity import note_fingerprint
from starlette.routing import Mount, Route
from starlette.staticfiles import StaticFiles


MAX_UPLOAD_BYTES = 32 * 1024 * 1024
MAX_CARDS = 50_000
MAX_REVIEWS = 1_000_000
MAX_ID = 2**53 - 1  # Keep identifiers exact in the browser as well as Python.
SESSION_SECONDS = 12 * 60 * 60
SESSION_COOKIE = "anki_dashboard_session"
_COOKIE_RE = re.compile(r"v1\.([0-9]{1,12})\.([A-Za-z0-9_-]{22})\.([A-Za-z0-9_-]{43})\Z")
_PBKDF2_ROUNDS = 600_000


@dataclass(frozen=True)
class DashboardConfig:
    password: str
    upload_token: str
    encryption_key: str
    data_dir: Path = Path(".dashboard-data")
    max_upload_bytes: int = MAX_UPLOAD_BYTES
    public_url: str = ""

    @classmethod
    def from_env(cls) -> "DashboardConfig":
        return cls(
            password=os.environ.get("DASHBOARD_PASSWORD", ""),
            upload_token=os.environ.get("ANKI_UPLOAD_TOKEN", ""),
            encryption_key=os.environ.get("DASHBOARD_ENCRYPTION_KEY", ""),
            data_dir=Path(os.environ.get("DASHBOARD_DATA_DIR", ".dashboard-data")),
            public_url=os.environ.get("DASHBOARD_PUBLIC_URL", ""),
        )

    def validate(self) -> None:
        if not isinstance(self.password, str) or not 12 <= len(self.password) <= 1024:
            raise ValueError("DASHBOARD_PASSWORD must contain between 12 and 1024 characters")
        if not isinstance(self.upload_token, str) or not 32 <= len(self.upload_token) <= 512:
            raise ValueError("ANKI_UPLOAD_TOKEN must contain between 32 and 512 characters")
        if not self.upload_token.isascii() or any(c.isspace() for c in self.upload_token):
            raise ValueError("ANKI_UPLOAD_TOKEN must be ASCII without whitespace")
        try:
            Fernet(self.encryption_key.encode("ascii"))
        except (ValueError, UnicodeError, AttributeError) as exc:
            raise ValueError("DASHBOARD_ENCRYPTION_KEY must be a valid Fernet key") from exc
        if type(self.max_upload_bytes) is not int or not 1024 <= self.max_upload_bytes <= MAX_UPLOAD_BYTES:
            raise ValueError("max_upload_bytes must be between 1024 and 33554432")
        if not isinstance(self.public_url, str):
            raise ValueError("DASHBOARD_PUBLIC_URL must be an HTTPS origin")
        if self.public_url:
            try:
                public = urlsplit(self.public_url)
                public.port  # Validate the port syntax and range.
                if public.hostname:
                    public.hostname.encode("idna")
                if (
                    public.scheme != "https" or not public.hostname
                    or public.username is not None or public.password is not None
                    or public.path not in {"", "/"} or public.query or public.fragment
                    or "\\" in self.public_url or any(c.isspace() or ord(c) < 32 for c in self.public_url)
                ):
                    raise ValueError
            except (TypeError, ValueError, UnicodeError):
                raise ValueError("DASHBOARD_PUBLIC_URL must be an HTTPS origin without credentials, path, query, or fragment") from None


class SnapshotValidationError(ValueError):
    """A bounded, user-visible validation error without any card contents."""


class _PlainText(HTMLParser):
    """Extract visible text without ever returning executable HTML or URLs."""

    hidden_tags = {"script", "style", "iframe", "object", "template", "noscript", "svg"}
    break_tags = {"br", "p", "div", "li", "tr", "hr", "h1", "h2", "h3", "h4"}

    def __init__(self, *, answer_only: bool = False) -> None:
        super().__init__(convert_charrefs=True)
        self.parts: list[str] = []
        self.hidden: list[str] = []
        self.answer_only = answer_only

    def _answer_boundary(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        # Anki's rendered answer often includes {{FrontSide}} before this
        # marker. Keep custom templates intact when no visible marker exists.
        if self.answer_only and not self.hidden and tag == "hr" and ("id", "answer") in attrs:
            self.parts.clear()
            self.answer_only = False

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        self._answer_boundary(tag, attrs)
        if tag in self.hidden_tags:
            self.hidden.append(tag)
        elif not self.hidden and tag in self.break_tags:
            self.parts.append("\n")

    def handle_endtag(self, tag: str) -> None:
        if self.hidden:
            if tag == self.hidden[-1]:
                self.hidden.pop()
        elif tag in self.break_tags:
            self.parts.append("\n")

    def handle_startendtag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        self._answer_boundary(tag, attrs)
        if not self.hidden and tag in self.break_tags:
            self.parts.append("\n")

    def handle_data(self, data: str) -> None:
        if not self.hidden:
            self.parts.append(data)


def _text(value: Any, label: str, limit: int, *, markup: bool = False, answer_only: bool = False) -> str:
    if not isinstance(value, str) or len(value) > limit or "\x00" in value:
        raise SnapshotValidationError(f"{label} must be text with at most {limit} characters")
    try:
        value.encode("utf-8")
    except UnicodeError:
        raise SnapshotValidationError(f"{label} must contain valid Unicode text") from None
    if markup:
        parser = _PlainText(answer_only=answer_only)
        parser.feed(value)
        parser.close()
        return re.sub(r"\n{3,}", "\n\n", "".join(parser.parts)).strip()
    return value


def _integer(value: Any, label: str, low: int = 0, high: int = MAX_ID) -> int:
    if type(value) is not int or not low <= value <= high:
        raise SnapshotValidationError(f"{label} must be an integer between {low} and {high}")
    return value


def validate_snapshot(value: Any) -> dict[str, Any]:
    """Validate snapshots and retain only safe text, formatting and raster media."""
    if not isinstance(value, dict) or type(value.get("schema_version")) is not int or value["schema_version"] != 1:
        raise SnapshotValidationError("schema_version must be 1")
    source = value.get("source")
    if not isinstance(source, dict) or source.get("kind") not in ("ankiconnect", "ankiweb"):
        raise SnapshotValidationError("source.kind must be ankiconnect or ankiweb")
    safe_source = {"profile": _text(source.get("profile"), "source.profile", 256), "kind": source["kind"]}
    if "timezone" in source:
        zone = _text(source["timezone"], "source.timezone", 128)
        try:
            ZoneInfo(zone)
        except (ZoneInfoNotFoundError, ValueError) as exc:
            raise SnapshotValidationError("source.timezone must be an IANA timezone") from exc
        safe_source["timezone"] = zone
    if "rollover_hour" in source:
        safe_source["rollover_hour"] = _integer(source["rollover_hour"], "source.rollover_hour", 0, 23)
    if "history_scope" in source:
        safe_source["history_scope"] = _text(source["history_scope"], "source.history_scope", 64)
    for field in ("orphan_review_count", "collection_review_count"):
        if field in source:
            safe_source[field] = _integer(source[field], "source." + field)
    synced_at = _text(value.get("synced_at"), "synced_at", 64)
    try:
        timestamp = datetime.fromisoformat(synced_at.replace("Z", "+00:00"))
        if timestamp.tzinfo is None:
            raise ValueError("missing timezone")
        # A canonical UTC timestamp also avoids parsing ambiguity in browsers.
        synced_at = timestamp.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")
    except (ValueError, OverflowError) as exc:
        raise SnapshotValidationError("synced_at must be an ISO 8601 timestamp with a timezone") from exc
    cards = value.get("cards")
    reviews = value.get("reviews")
    if not isinstance(cards, list) or len(cards) > MAX_CARDS:
        raise SnapshotValidationError(f"cards must be a list with at most {MAX_CARDS} entries")
    if not isinstance(reviews, list) or len(reviews) > MAX_REVIEWS:
        raise SnapshotValidationError(f"reviews must be a list with at most {MAX_REVIEWS} entries")
    try:
        media = validate_media(value.get("media", {}))
    except ValueError as exc:
        raise SnapshotValidationError(str(exc)) from None
    referenced = set()
    safe_cards: list[dict[str, Any]] = []
    card_ids: set[int] = set()
    for card in cards:
        if not isinstance(card, dict):
            raise SnapshotValidationError("each card must be an object")
        card_id = _integer(card.get("id"), "card.id", 1)
        if card_id in card_ids:
            raise SnapshotValidationError("card ids must be unique")
        card_ids.add(card_id)
        tags = card.get("tags")
        fields = card.get("fields", {})
        if not isinstance(tags, list) or len(tags) > 128:
            raise SnapshotValidationError("card.tags must be a list with at most 128 entries")
        if not isinstance(fields, dict) or len(fields) > 64:
            raise SnapshotValidationError("card.fields must be an object with at most 64 entries")
        suspended = card.get("suspended", False)
        if type(suspended) is not bool:
            raise SnapshotValidationError("card.suspended must be a boolean")
        model = _text(card.get("model", ""), "card.model", 256)
        raw_fields = {_text(k, "field name", 256): _text(v, "field value", 128_000) for k, v in fields.items()}
        identity = card.get("tag_identity")
        if identity is not None and (not isinstance(identity, str) or re.fullmatch(r"[a-f0-9]{64}", identity) is None):
            raise SnapshotValidationError("card.tag_identity must be a SHA-256 fingerprint")
        safe_cards.append({
            "id": card_id,
            "note_id": _integer(card.get("note_id"), "card.note_id", 1),
            "deck": _text(card.get("deck"), "card.deck", 512),
            "model": model,
            "tag_identity": identity or note_fingerprint(model, raw_fields),
            "tags": list(dict.fromkeys(_text(tag, "card.tag", 512) for tag in tags)),
            "front": _text(card.get("front"), "card.front", 128_000, markup=True),
            "back": _text(card.get("back"), "card.back", 128_000, markup=True, answer_only=True),
            "fields": {_text(k, "field name", 256): _text(v, "field value", 128_000, markup=True) for k, v in fields.items()},
            "reps": _integer(card.get("reps", 0), "card.reps"),
            "lapses": _integer(card.get("lapses", 0), "card.lapses"),
            "interval": _integer(card.get("interval", 0), "card.interval", -MAX_ID),
            "due": _integer(card.get("due", 0), "card.due", -MAX_ID),
            "suspended": suspended,
        })
        if "editable_fields" in card:
            editable = card["editable_fields"]
            if not isinstance(editable, dict) or not 1 <= len(editable) <= 64 or set(editable) != set(fields):
                raise SnapshotValidationError("invalid editable fields")
            editable = {_text(k, "field name", 256): _text(v, "field value", 128_000) for k, v in editable.items()}
            if note_fingerprint(model, editable) != safe_cards[-1]["tag_identity"]:
                raise SnapshotValidationError("editable fields do not match the original note")
            safe_cards[-1]["editable_fields"] = editable
        for field in ("queue", "type", "ease_factor", "added_at"):
            if field in card:
                safe_cards[-1][field] = _integer(card[field], "card." + field, -MAX_ID)
        if "due_date" in card:
            date = _text(card["due_date"], "card.due_date", 10)
            try:
                datetime.strptime(date, "%Y-%m-%d")
            except ValueError:
                raise SnapshotValidationError("card.due_date must be YYYY-MM-DD") from None
            safe_cards[-1]["due_date"] = date
        for field in ("stability", "difficulty", "desired_retention", "retrievability"):
            if field in card:
                number = card[field]
                if type(number) not in (int, float) or not math.isfinite(number) or not 0 <= number <= MAX_ID:
                    raise SnapshotValidationError("invalid card." + field)
                safe_cards[-1][field] = number
        for side in ("front", "back"):
            html, refs = rich(card[side], media, answer_only=side == "back")
            safe_cards[-1][side + "_html"] = html
            referenced.update(refs)
    orphans = value.get("orphan_reviews", [])
    if not isinstance(orphans, list) or len(reviews) + len(orphans) > MAX_REVIEWS:
        raise SnapshotValidationError("combined review count exceeds limit")
    if orphans and (safe_source["kind"] != "ankiweb" or safe_source.get("history_scope") != "collection"):
        raise SnapshotValidationError("orphan_reviews require a complete collection export")
    safe_reviews: list[dict[str, int]] = []
    safe_orphans: list[dict[str, int]] = []
    review_ids: set[int] = set()
    for is_orphan, entries, target in ((False, reviews, safe_reviews), (True, orphans, safe_orphans)):
        for review in entries:
            if not isinstance(review, dict):
                raise SnapshotValidationError("each review must be an object")
            review_id = _integer(review.get("id"), "review.id", 1)
            card_id = _integer(review.get("card_id"), "review.card_id", 1)
            if review_id in review_ids:
                raise SnapshotValidationError("review ids must be unique")
            if not is_orphan and card_id not in card_ids:
                raise SnapshotValidationError("review.card_id must refer to an included card")
            if is_orphan and card_id in card_ids:
                raise SnapshotValidationError("orphan review must refer to a missing card")
            review_ids.add(review_id)
            target.append({
                "id": review_id,
                "card_id": card_id,
                "ease": _integer(review.get("ease"), "review.ease", 0, 4),
                "time_ms": _integer(review.get("time_ms"), "review.time_ms", 0, 86_400_000),
                "type": _integer(review.get("type"), "review.type", 0, 5),
            })
            for field in ("interval", "last_interval", "ease_factor"):
                if field in review:
                    target[-1][field] = _integer(review[field], "review." + field, -MAX_ID)
    result = {"schema_version": 1, "source": safe_source, "synced_at": synced_at, "cards": safe_cards, "reviews": safe_reviews}
    if safe_orphans:
        result["orphan_reviews"] = safe_orphans
    if "native_statistics" in value:
        native = value["native_statistics"]
        # Data only; never rendered as markup or interpreted as executable content.
        try:
            if not isinstance(native, dict) or len(json.dumps(native, allow_nan=False)) > 2_000_000:
                raise ValueError()
            result["native_statistics"] = json.loads(json.dumps(native, allow_nan=False))
        except (ValueError, TypeError, RecursionError):
            raise SnapshotValidationError("invalid native_statistics") from None
    used_media = {name: item for name, item in media.items() if name in referenced}
    if used_media:
        result["media"] = used_media
    return result


def _bad_constant(value: str) -> None:
    raise ValueError("non-finite JSON number")


def _unique_object(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("duplicate JSON key")
        result[key] = value
    return result


async def _json_body(request: Request, limit: int) -> Any:
    media_type = request.headers.get("content-type", "").split(";", 1)[0].strip().lower()
    if media_type != "application/json":
        raise HTTPException(415, "Content-Type must be application/json")
    content_length = request.headers.get("content-length")
    if content_length is not None:
        try:
            length = int(content_length)
        except ValueError:
            raise HTTPException(400, "Invalid Content-Length") from None
        if length < 0:
            raise HTTPException(400, "Invalid Content-Length")
        if length > limit:
            raise HTTPException(413, "Request is too large")
    chunks = bytearray()
    async for chunk in request.stream():
        if len(chunks) + len(chunk) > limit:
            raise HTTPException(413, "Request is too large")
        chunks.extend(chunk)
    try:
        return json.loads(chunks, parse_constant=_bad_constant, object_pairs_hook=_unique_object)
    except (ValueError, UnicodeError, RecursionError):
        raise HTTPException(400, "Invalid JSON") from None


class SnapshotStore:
    def __init__(self, config: DashboardConfig) -> None:
        self.directory = Path(config.data_dir)
        self.path = self.directory / "snapshot.fernet"
        self.fernet = Fernet(config.encryption_key.encode("ascii"))
        self.max_bytes = config.max_upload_bytes

    def read(self) -> dict[str, Any] | None:
        try:
            if self.path.stat().st_size > self.max_bytes * 2:
                raise ValueError("stored snapshot exceeds limit")
            encrypted = self.path.read_bytes()
        except FileNotFoundError:
            return None
        clear = self.fernet.decrypt(encrypted)
        # Only validated, authenticated snapshots are written by this process.
        return json.loads(clear, parse_constant=_bad_constant, object_pairs_hook=_unique_object)

    def write(self, snapshot: dict[str, Any]) -> None:
        encoded = json.dumps(snapshot, ensure_ascii=False, separators=(",", ":"), allow_nan=False).encode("utf-8")
        if len(encoded) > self.max_bytes:
            raise SnapshotValidationError("Normalized snapshot is too large")
        encrypted = self.fernet.encrypt(encoded)
        self.directory.mkdir(mode=0o700, parents=True, exist_ok=True)
        temporary: str | None = None
        try:
            with tempfile.NamedTemporaryFile(mode="wb", dir=self.directory, prefix=".upload-", delete=False) as handle:
                temporary = handle.name
                handle.write(encrypted)
                handle.flush()
                os.fsync(handle.fileno())
            os.replace(temporary, self.path)
            temporary = None
        finally:
            if temporary is not None:
                Path(temporary).unlink(missing_ok=True)


class _LoginLimiter:
    """Bound password hashing work; IPs come from ASGI, never client headers."""

    def __init__(self) -> None:
        self.attempts: dict[str, deque[float]] = defaultdict(deque)
        self.global_attempts: deque[float] = deque()

    def admit(self, address: str) -> None:
        now = time.monotonic()
        for key in list(self.attempts):
            if not self.attempts[key] or self.attempts[key][-1] <= now - 60:
                del self.attempts[key]
        while self.global_attempts and self.global_attempts[0] <= now - 60:
            self.global_attempts.popleft()
        if len(self.attempts) >= 1024 and address not in self.attempts:
            raise HTTPException(429, "Please wait before trying again", headers={"Retry-After": "60"})
        entries = self.attempts[address]
        while entries and entries[0] <= now - 60:
            entries.popleft()
        if len(entries) >= 5 or len(self.global_attempts) >= 100:
            raise HTTPException(429, "Please wait before trying again", headers={"Retry-After": "60"})
        entries.append(now)
        self.global_attempts.append(now)


class _OwnerSessions:
    def __init__(self, config: DashboardConfig) -> None:
        material = config.encryption_key.encode("ascii")
        self.salt = hashlib.sha256(b"anki-dashboard-password-v1" + material).digest()
        self.password_hash = self.password_digest(config.password)
        self.signing_key = hmac.digest(material, b"anki-dashboard-session-v1" + self.password_hash, "sha256")

    def password_digest(self, password: str) -> bytes:
        return hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), self.salt, _PBKDF2_ROUNDS)

    def matches(self, password: str) -> bool:
        return hmac.compare_digest(self.password_digest(password), self.password_hash)

    def issue(self) -> str:
        payload = f"v1.{int(time.time())}.{secrets.token_urlsafe(16)}"
        signature = base64.urlsafe_b64encode(hmac.digest(self.signing_key, payload.encode("ascii"), "sha256")).rstrip(b"=")
        return f"{payload}.{signature.decode('ascii')}"

    def authenticated(self, request: Request) -> bool:
        cookie = request.cookies.get(SESSION_COOKIE, "")
        match = _COOKIE_RE.fullmatch(cookie)
        if match is None:
            return False
        issued = int(match.group(1))
        age = time.time() - issued
        if age < -60 or age > SESSION_SECONDS:
            return False
        payload, signature = cookie.rsplit(".", 1)
        expected = base64.urlsafe_b64encode(hmac.digest(self.signing_key, payload.encode("ascii"), "sha256")).rstrip(b"=").decode("ascii")
        return hmac.compare_digest(expected, signature)


def _same_origin(request: Request, public_origin: str = "") -> None:
    # Browsers send Origin for fetch POSTs.  Requiring it also fails closed for
    # HTML form posts and opaque origins; the connector uses bearer auth instead.
    expected = public_origin or str(request.base_url).rstrip("/")
    if request.headers.get("origin") != expected:
        raise HTTPException(403, "A same-origin request is required")


def create_dashboard(config: DashboardConfig | None = None) -> Starlette:
    config = config or DashboardConfig.from_env()
    config.validate()
    public_origin = ""
    if config.public_url:
        public = urlsplit(config.public_url)
        hostname = public.hostname.encode("idna").decode("ascii")
        authority = f"[{hostname}]" if ":" in hostname else hostname
        if public.port is not None and public.port != 443:
            authority += f":{public.port}"
        public_origin = f"https://{authority}"
    sessions = _OwnerSessions(config)
    limiter = _LoginLimiter()
    store = SnapshotStore(config)

    def require_owner(request: Request) -> None:
        if not sessions.authenticated(request):
            raise HTTPException(401, "Please sign in")

    async def session(request: Request) -> JSONResponse:
        return JSONResponse({"authenticated": sessions.authenticated(request), "configured": True})

    async def login(request: Request) -> JSONResponse:
        _same_origin(request, public_origin)
        limiter.admit(request.client.host if request.client else "unknown")
        body = await _json_body(request, 8192)
        password = body.get("password") if isinstance(body, dict) else None
        if not isinstance(password, str) or len(password) > 1024:
            raise HTTPException(400, "A password is required")
        try:
            password.encode("utf-8")
        except UnicodeError:
            raise HTTPException(400, "A password must contain valid Unicode text") from None
        if not await run_in_threadpool(sessions.matches, password):
            raise HTTPException(401, "Password is incorrect")
        response = JSONResponse({"authenticated": True})
        response.set_cookie(SESSION_COOKIE, sessions.issue(), max_age=SESSION_SECONDS, httponly=True, secure=bool(public_origin) or request.url.scheme == "https", samesite="strict", path="/")
        return response

    async def logout(request: Request) -> JSONResponse:
        _same_origin(request, public_origin)
        response = JSONResponse({"authenticated": False})
        response.delete_cookie(SESSION_COOKIE, path="/", httponly=True, secure=bool(public_origin) or request.url.scheme == "https", samesite="strict")
        return response

    async def get_snapshot(request: Request) -> JSONResponse:
        require_owner(request)
        try:
            snapshot = await run_in_threadpool(store.read)
        except (OSError, InvalidToken, ValueError, UnicodeError, RecursionError):
            raise HTTPException(503, "Stored data cannot be read; check the storage and encryption key") from None
        if snapshot:
            snapshot = {k: v for k, v in snapshot.items() if k != "media"}
        return JSONResponse({"snapshot": snapshot})

    async def get_media(request: Request) -> Response:
        require_owner(request)
        media_id = request.path_params["media_id"]
        if not re.fullmatch(r"[a-f0-9]{64}", media_id):
            raise HTTPException(404, "Image not found")
        try:
            snapshot = await run_in_threadpool(store.read)
        except (OSError, InvalidToken, ValueError):
            raise HTTPException(503, "Stored images cannot be read") from None
        for item in (snapshot or {}).get("media", {}).values():
            if item["id"] == media_id:
                return Response(base64.b64decode(item["data"]), media_type=item["mime"])
        raise HTTPException(404, "Image not found")

    async def upload_snapshot(request: Request) -> JSONResponse:
        authorization = request.headers.get("authorization", "")
        expected = f"Bearer {config.upload_token}".encode("ascii")
        if not hmac.compare_digest(authorization.encode("utf-8"), expected):
            raise HTTPException(401, "A valid upload token is required")
        body = await _json_body(request, config.max_upload_bytes)
        try:
            # A download-only AnkiWeb refresh has no media sync. Keep previously
            # validated local attachments only while cards still reference them.
            if isinstance(body, dict) and isinstance(body.get("source"), dict) and body["source"].get("kind") == "ankiweb" and "media" not in body:
                previous = await run_in_threadpool(store.read)
                if previous and previous.get("media"):
                    body["media"] = previous["media"]
            snapshot = await run_in_threadpool(validate_snapshot, body)
            await run_in_threadpool(store.write, snapshot)
        except SnapshotValidationError as exc:
            raise HTTPException(422, str(exc)) from None
        except OSError:
            raise HTTPException(503, "Data could not be saved; check the storage") from None
        return JSONResponse({"ok": True, "cards": len(snapshot["cards"]), "reviews": len(snapshot["reviews"]) + len(snapshot.get("orphan_reviews", [])), "synced_at": snapshot["synced_at"]})

    async def health(request: Request) -> JSONResponse:
        return JSONResponse({"status": "ok"})

    async def errors(request: Request, exc: HTTPException) -> JSONResponse:
        return JSONResponse({"error": exc.detail}, status_code=exc.status_code, headers=exc.headers)

    routes = [
        Route("/api/health", health, methods=["GET"]),
        Route("/api/session", session, methods=["GET"]),
        Route("/api/login", login, methods=["POST"]),
        Route("/api/logout", logout, methods=["POST"]),
        Route("/api/snapshot", get_snapshot, methods=["GET"]),
        Route("/api/media/{media_id}", get_media, methods=["GET"]),
        Route("/api/snapshot", upload_snapshot, methods=["POST"]),
    ]
    web = Path(__file__).resolve().parent / "web"
    if web.is_dir():
        routes.append(Mount("/", app=StaticFiles(directory=web, html=True), name="web"))
    application = Starlette(routes=routes, exception_handlers={HTTPException: errors})

    async def security_headers(request: Request, call_next: Any) -> Any:
        response = await call_next(request)
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["Referrer-Policy"] = "no-referrer"
        response.headers["X-Frame-Options"] = "DENY"
        response.headers["Content-Security-Policy"] = "default-src 'self'; script-src 'self'; style-src 'self'; img-src 'self' data:; connect-src 'self'; object-src 'none'; base-uri 'none'; frame-ancestors 'none'; form-action 'self'"
        if request.url.path.startswith("/api/"):
            response.headers["Cache-Control"] = "no-store"
        return response

    application.add_middleware(BaseHTTPMiddleware, dispatch=security_headers)
    application.state.config = config
    return application


class _EnvironmentDashboard:
    """Defer reading secrets until ASGI startup; imports remain side-effect free."""

    def __init__(self) -> None:
        self.application: Starlette | None = None

    async def __call__(self, scope: Any, receive: Any, send: Any) -> None:
        if self.application is None:
            self.application = create_dashboard()
        await self.application(scope, receive, send)


app = _EnvironmentDashboard()
