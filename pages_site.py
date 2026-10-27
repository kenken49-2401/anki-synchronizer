"""Build a static Pages site containing ciphertext, never plaintext snapshots."""
from __future__ import annotations

import argparse
from collections.abc import Iterable
from contextlib import contextmanager
from html import escape
import hashlib
import json
import os
from pathlib import Path
import re
import sys
import tempfile
import time
from zoneinfo import ZoneInfo
from urllib.parse import urlsplit

import httpx
from anki import errors as anki_errors

from card_media import MAX_TOTAL_BYTES, MAX_MEDIA_FILES, validate_media
from cloud_sync import export_snapshot as export_ankiweb
from connector import ConnectorError, export_snapshot as export_local
from dashboard import SnapshotValidationError, validate_snapshot
from pages_crypto import MAX_PACKAGE_BYTES, PackageError, decrypt, encrypt, password_bytes

ROOT = Path(__file__).resolve().parent
PACKAGE_NAME = "snapshot.enc.json"
ASSETS = {"index.html", "app.js", "styles.css", "stats.mjs", "vault.mjs", "tags.mjs", "tag-queue.mjs", "updates.mjs",
          "device-session.mjs", "anki-insights.mjs", "anki-insights.css",
          "note-edits.mjs", "note-editor.mjs",
          "rich-note-field.mjs",
          "manifest.webmanifest", "icon-180.png", "icon-192.png", "icon-512.png"}
BUILD_FILE = "release.json"
MEDIA_FILE = re.compile(r"media-[a-f0-9]{64}\.enc\.json")
MEDIA_CHUNK_BYTES = 4 * 1024 * 1024
MAX_MEDIA_PACKAGES = 256


def load_package(path: Path, password: str) -> dict:
    if path.stat().st_size > MAX_PACKAGE_BYTES:
        raise PackageError("Encrypted input exceeds the size limit.")
    try:
        value = json.loads(path.read_bytes())
    except (ValueError, UnicodeError):
        raise PackageError("Invalid encrypted input file.") from None
    snapshot = decrypt(value, password)
    def read_chunk(name):
        chunk = path.parent / name
        if chunk.is_symlink() or chunk.stat().st_size > MAX_PACKAGE_BYTES:
            raise PackageError("Invalid encrypted image chunk.")
        return json.loads(chunk.read_bytes())
    return hydrate_media(snapshot, password, read_chunk)


def fetch_previous(url: str, password: str, *, include_media: bool = True) -> dict | None:
    """Fetch public ciphertext without transmitting a password or token."""
    parsed = urlsplit(url)
    if (parsed.scheme != "https" or not parsed.hostname or parsed.username is not None
            or parsed.password is not None or parsed.query or parsed.fragment):
        raise PackageError("Previous Pages URL must use HTTPS without credentials or query parameters.")
    destination = url.rstrip("/") + "/" + PACKAGE_NAME
    try:
        with httpx.Client(timeout=60, follow_redirects=False) as client:
            def read_url(destination, allow_missing=False):
                with client.stream("GET", destination) as response:
                    if allow_missing and response.status_code == 404:
                        return None
                    response.raise_for_status()
                    chunks = bytearray()
                    for chunk in response.iter_bytes():
                        if len(chunks) + len(chunk) > MAX_PACKAGE_BYTES:
                            raise PackageError("Previous encrypted package exceeds the size limit.")
                        chunks.extend(chunk)
                return json.loads(chunks)
            package = read_url(destination, allow_missing=True)
            if package is None:
                return None
            snapshot = decrypt(package, password)
            if include_media:
                return hydrate_media(snapshot, password, lambda name: read_url(url.rstrip("/") + "/" + name))
            return snapshot
    except PackageError:
        raise
    except Exception:
        raise PackageError("Previous Pages data could not be read; existing deployment was preserved.") from None



def hydrate_media(snapshot: dict, password: str, read_chunk) -> dict:
    packages = snapshot.get("media_packages", [])
    if not isinstance(packages, list) or len(packages) > MAX_MEDIA_PACKAGES or any(not isinstance(name, str) for name in packages) or len(set(packages)) != len(packages):
        raise PackageError("Invalid encrypted image manifest.")
    media = dict(snapshot.get("media", {}))
    total = sum((len(item["data"]) * 3 // 4 - item["data"].count("=")) for item in media.values())
    for name in packages:
        if not isinstance(name, str) or not MEDIA_FILE.fullmatch(name):
            raise PackageError("Invalid encrypted image manifest.")
        part = decrypt(read_chunk(name), password)
        if part.get("schema_version") != 1 or not isinstance(part.get("media"), dict):
            raise PackageError("Invalid encrypted image chunk.")
        additions = validate_media(part["media"])
        if len(media) + len(additions) > MAX_MEDIA_FILES:
            raise PackageError("Encrypted image count exceeds the supported limit.")
        if media.keys() & additions.keys():
            raise PackageError("Duplicate encrypted images.")
        total += sum((len(item["data"]) * 3 // 4 - item["data"].count("=")) for item in additions.values())
        if total > MAX_TOTAL_BYTES:
            raise PackageError("Encrypted images exceed the total size limit.")
        media.update(additions)
    if packages:
        snapshot = {**snapshot, "media": validate_media(media)}
        snapshot.pop("media_packages", None)
        snapshot.pop("media_index", None)
        snapshot.pop("media_names", None)
    return snapshot


def split_media(snapshot: dict, password: str) -> tuple[dict, dict[str, bytes]]:
    media = snapshot.get("media", {})
    if sum(len(item["data"]) + len(name) + 512 for name, item in media.items()) <= MEDIA_CHUNK_BYTES:
        return snapshot, {}
    chunks = {}
    index = {}
    batch = {}
    size = 0
    def finish():
        encoded = json.dumps(encrypt({"schema_version": 1, "media": batch}, password), separators=(",", ":")).encode()
        name = "media-" + hashlib.sha256(encoded).hexdigest() + ".enc.json"
        chunks[name] = encoded
        for item in batch.values():
            index[item["id"]] = name
    for name, item in sorted(media.items()):
        cost = len(item["data"]) + len(name) + 512
        if batch and size + cost > MEDIA_CHUNK_BYTES:
            finish()
            batch, size = {}, 0
        batch[name] = item
        size += cost
    if batch:
        finish()
    if len(chunks) > MAX_MEDIA_PACKAGES:
        raise PackageError("Too many encrypted image chunks.")
    names = {name: item['id'] for name, item in media.items()}
    return {**snapshot, "media": {}, "media_packages": list(chunks), "media_index": index, "media_names": names}, chunks


def restore_source(snapshot: dict) -> dict:
    """Revalidate saved rich HTML with its original, encrypted media filenames."""
    media = validate_media(snapshot.get("media", {}))
    names = {item["id"]: name for name, item in media.items()}
    restored = dict(snapshot)
    restored["cards"] = []
    pattern = re.compile(r'src="\./api/media/([a-f0-9]{64})"')
    for card in snapshot.get("cards", []):
        copied = dict(card)
        for side in ("front", "back"):
            if side + "_html" in card:
                copied[side] = pattern.sub(
                    lambda match: 'src="' + escape(names.get(match[1], ""), quote=True) + '"', card[side + "_html"])
        restored["cards"].append(copied)
    return restored


def prepare_snapshot(raw: dict, previous: Iterable[dict] = ()) -> dict:
    """Latest content wins; retain only referenced images from older packages."""
    media = {}
    if not raw.get("media_complete"):
        for prior in previous:
            media.update(prior.get("media", {}))
    media.update(raw.get("media", {}))
    return validate_snapshot({**raw, "media": media})


def _atomic_write(path: Path, contents: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = None
    try:
        with tempfile.NamedTemporaryFile(dir=path.parent, delete=False) as output:
            temporary = Path(output.name)
            output.write(contents)
            output.flush()
            os.fsync(output.fileno())
        os.replace(temporary, path)
        temporary = None
        # Ciphertext and public assets must be readable by the Pages web server.
        path.chmod(0o644)
    finally:
        if temporary is not None:
            temporary.unlink(missing_ok=True)


def build_site(snapshot: dict, password: str, output: Path, *, seed_output: Path | None = None) -> None:
    if seed_output is not None and (seed_output.name != PACKAGE_NAME or seed_output.is_symlink()):
        raise PackageError("Seed output must be a regular snapshot.enc.json file.")
    compact, chunks = split_media(snapshot, password)
    package = json.dumps(encrypt(compact, password), separators=(",", ":")).encode()
    if len(package) > MAX_PACKAGE_BYTES:
        raise PackageError("Encrypted package exceeds the size limit.")
    # Never delete or publish an unknown directory that may contain private files.
    if output.is_symlink() or (output.exists() and (
            not output.is_dir() or any((p.name not in ASSETS | {PACKAGE_NAME, ".nojekyll", BUILD_FILE} and not MEDIA_FILE.fullmatch(p.name))
                                      or p.is_symlink() or not p.is_file() for p in output.iterdir()))):
        raise PackageError("Output must be a dedicated site directory with no unknown files or symlinks.")
    write_public_assets(output)
    for name, content in chunks.items():
        _atomic_write(output / name, content)
    _atomic_write(output / PACKAGE_NAME, package)
    for old in output.iterdir():
        if MEDIA_FILE.fullmatch(old.name) and old.name not in chunks:
            old.unlink()
    if seed_output is not None:
        for name, content in chunks.items():
            _atomic_write(seed_output.parent / name, content)
        _atomic_write(seed_output, package)


def write_public_assets(output: Path, *, setup_pending: bool = False) -> None:
    """Write only the allowlisted public interface, without accessing Anki or secrets."""
    output.mkdir(parents=True, exist_ok=True)
    assets = {name: (ROOT / "web" / name).read_bytes() for name in sorted(ASSETS)}
    if setup_pending:
        assets["index.html"] = assets["index.html"].replace(b"<head>", b'<head><meta name="anki-atlas-setup" content="pending">')
    digest = hashlib.sha256()
    for name, content in assets.items():
        digest.update(name.encode() + b"\0" + str(len(content)).encode() + b"\0" + content)
    version = digest.hexdigest()
    for name, content in assets.items():
        if name.endswith((".html", ".js", ".mjs", ".css")):
            text = content.decode("utf-8").replace("__ATLAS_BUILD__", version)
            text = re.sub(r'(["\'])\./([A-Za-z0-9_.-]+\.(?:mjs|js|css))\1',
                          lambda m: m[1] + './' + m[2] + '?v=' + version + m[1], text)
            content = text.encode("utf-8")
        _atomic_write(output / name, content)
    _atomic_write(output / BUILD_FILE, json.dumps({"schema_version": 1, "version": version}, separators=(",", ":")).encode())
    _atomic_write(output / ".nojekyll", b"")




@contextmanager
def anki_timezone(zone: str):
    """Use the requested timezone for Anki's native scheduler and graphs."""
    ZoneInfo(zone)
    if not hasattr(time, "tzset"):
        yield
        return
    previous = os.environ.get("TZ")
    try:
        os.environ["TZ"] = zone
        time.tzset()
        yield
    finally:
        if previous is None:
            os.environ.pop("TZ", None)
        else:
            os.environ["TZ"] = previous
        time.tzset()

def report_failure(stage: str, error: Exception) -> None:
    # Emit fixed labels only. Exception messages/URLs/locals may contain private data.
    safe_messages = {
        "Set ANKIWEB_HKEY to an AnkiWeb sync token.": "ANKIWEB_HKEY is missing or malformed.",
        "AnkiWeb endpoint must be an HTTPS ankiweb.net subdomain URL.": "ANKIWEB_ENDPOINT is invalid; copy only its value from secrets.env.",
        "PAGES_PASSWORD must contain 16 to 1024 UTF-8 bytes; use a long random password.": "PAGES_PASSWORD is missing or outside the supported length.",
        "Create an encrypted seed using the local AnkiConnect importer first.": "No encrypted seed exists. Select source=ankiweb for an AnkiWeb import.",
        "Referenced image count exceeds the supported limit; narrow the collection query.": "Referenced image count exceeds the supported limit.",
        "Referenced images exceed the total image byte limit.": "Referenced images exceed the total supported image size.",
        "Cannot decrypt the package; check the password and file integrity.": "The previous data cannot be decrypted with PAGES_PASSWORD.",
        "Previous Pages data could not be read; existing deployment was preserved.": "Could not retrieve previous encrypted data; deployment was preserved.",
    }
    labels = []
    current = error
    for _ in range(4):
        if current is None:
            break
        label = safe_messages.get(str(current))
        if label:
            labels.append(label)
        for name in ("SyncError", "NetworkError", "DBError", "BackendIOError", "InvalidInput", "TemplateError", "NotFoundError", "Interrupted"):
            if isinstance(current, getattr(anki_errors, name)):
                labels.append(name)
                if name == "SyncError":
                    labels.append("authentication rejected" if current.kind == anki_errors.SyncErrorKind.AUTH else "sync server rejected the operation")
                if name in {"SyncError", "NetworkError"}:
                    for hint in ("timeout", "timed out", "certificate", "dns", "redirect", "connection", "upgrade", "empty", "full sync", "too large", "missing original size", "sync not started"):
                        if hint in str(current).lower():
                            labels.append(hint)
                    for match in re.finditer(r"\b(?:code|status)\s*[:=]\s*([1-5][0-9]{2})\b", str(current)):
                        labels.append(f"HTTP {match[1]}")
                break
        if isinstance(current, httpx.HTTPStatusError):
            labels.append(f"HTTP {current.response.status_code}")
        for kind in (AttributeError, TypeError, ValueError, OSError, RuntimeError):
            if type(current) is kind:
                labels.append(kind.__name__)
                break
        trace = current.__traceback__
        while trace:
            file = Path(trace.tb_frame.f_code.co_filename)
            if file.parent == ROOT and file.name in {"pages_site.py", "cloud_sync.py", "anki_media.py", "dashboard.py", "connector.py", "card_media.py"}:
                labels.append(f"{file.name}:{trace.tb_lineno}")
            trace = trace.tb_next
        current = current.__cause__ or current.__context__
    message = f"Pages build failed during {stage}. " + " / ".join(labels)
    print(message, file=sys.stderr, flush=True)
    if os.environ.get("GITHUB_ACTIONS") == "true":
        print(f"::error title=Anki Pages diagnostic::{message}", flush=True)


def progress(stage: str) -> str:
    print(f"Pages: {stage}", flush=True)
    if os.environ.get("GITHUB_ACTIONS") == "true":
        print(f"::notice title=Anki Pages progress::{stage}", flush=True)
    return stage

def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", choices=("ankiweb", "ankiconnect", "seed"), default="ankiweb")
    parser.add_argument("--output", type=Path, default=Path("site"))
    parser.add_argument("--seed", type=Path, default=Path("pages-data") / PACKAGE_NAME)
    parser.add_argument("--seed-output", type=Path)
    parser.add_argument("--previous-url", default=os.environ.get("PAGES_URL", ""))
    parser.add_argument("--timezone", default=os.environ.get("ANKI_TIMEZONE", "Asia/Tokyo"))
    parser.add_argument("--query", default="")
    parser.add_argument("--profile")
    parser.add_argument("--allow-empty", action="store_true")
    parser.add_argument("--cached-media-only", action="store_true", help="Explicitly reuse seed/previous images without accessing the media server")
    parser.add_argument("--discard-previous", action="store_true", default=os.environ.get("PAGES_DISCARD_PREVIOUS") == "true",
                        help="Explicit fresh import for password rotation; ignore old seeds and deployment")
    args = parser.parse_args(argv)
    stage = progress("checking configuration")
    try:
        password = os.environ.get("PAGES_PASSWORD", "")
        password_bytes(password)  # Fail before contacting Anki or writing files.
        stage = progress("reading previous encrypted data")
        previous = []
        if args.seed.exists() and not args.discard_previous:
            previous.append(load_package(args.seed, password))
        if args.previous_url and not args.discard_previous:
            prior = fetch_previous(args.previous_url, password, include_media=args.source != "ankiweb" or args.cached_media_only)
            if prior:
                previous.append(prior)
        if args.source == "ankiweb":
            stage = progress("downloading and reading AnkiWeb collection")
            with anki_timezone(args.timezone):
                raw = export_ankiweb(os.environ.get("ANKIWEB_HKEY", ""), os.environ.get("ANKIWEB_ENDPOINT") or None,
                                     timezone=args.timezone, query=args.query, allow_empty=args.allow_empty)
            if not args.cached_media_only:
                stage = progress("downloading referenced images")
                from anki_media import download_media
                raw["media"] = download_media(raw, os.environ.get("ANKIWEB_HKEY", ""), os.environ.get("ANKIWEB_ENDPOINT") or None)
                raw["media_complete"] = True
        elif args.source == "ankiconnect":
            stage = progress("reading local AnkiConnect")
            raw = export_local(api_key=os.environ.get("ANKI_CONNECT_API_KEY"), expected_profile=args.profile,
                               timezone=args.timezone, query=args.query)
        else:
            if not previous:
                raise PackageError("Create an encrypted seed using the local AnkiConnect importer first.")
            raw = restore_source(previous[-1])
        stage = progress("validating cards, reviews and images")
        snapshot = prepare_snapshot(raw, previous)
        stage = progress("encrypting and writing public site")
        build_site(snapshot, password, args.output, seed_output=args.seed_output)
        print("Encrypted Pages site built. No plaintext collection or credentials were published.")
        return 0
    except Exception as exc:
        report_failure(stage, exc)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
