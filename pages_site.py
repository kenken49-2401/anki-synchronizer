"""Build a static Pages site containing ciphertext, never plaintext snapshots."""
from __future__ import annotations

import argparse
from collections.abc import Iterable
from html import escape
import json
import os
from pathlib import Path
import re
import sys
import tempfile
from urllib.parse import urlsplit

import httpx

from card_media import validate_media
from cloud_sync import export_snapshot as export_ankiweb
from connector import ConnectorError, export_snapshot as export_local
from dashboard import SnapshotValidationError, validate_snapshot
from pages_crypto import MAX_PACKAGE_BYTES, PackageError, decrypt, encrypt, password_bytes

ROOT = Path(__file__).resolve().parent
PACKAGE_NAME = "snapshot.enc.json"
ASSETS = {"index.html", "app.js", "styles.css", "stats.mjs", "vault.mjs"}


def load_package(path: Path, password: str) -> dict:
    if path.stat().st_size > MAX_PACKAGE_BYTES:
        raise PackageError("Encrypted input exceeds the size limit.")
    try:
        value = json.loads(path.read_bytes())
    except (ValueError, UnicodeError):
        raise PackageError("Invalid encrypted input file.") from None
    return decrypt(value, password)


def fetch_previous(url: str, password: str) -> dict | None:
    """Fetch public ciphertext without transmitting a password or token."""
    parsed = urlsplit(url)
    if (parsed.scheme != "https" or not parsed.hostname or parsed.username is not None
            or parsed.password is not None or parsed.query or parsed.fragment):
        raise PackageError("Previous Pages URL must use HTTPS without credentials or query parameters.")
    destination = url.rstrip("/") + "/" + PACKAGE_NAME
    try:
        with httpx.Client(timeout=60, follow_redirects=False) as client:
            with client.stream("GET", destination) as response:
                if response.status_code == 404:
                    return None  # First deployment only.
                response.raise_for_status()
                chunks = bytearray()
                for chunk in response.iter_bytes():
                    if len(chunks) + len(chunk) > MAX_PACKAGE_BYTES:
                        raise PackageError("Previous encrypted package exceeds the size limit.")
                    chunks.extend(chunk)
        return decrypt(json.loads(chunks), password)
    except PackageError:
        raise
    except Exception:
        raise PackageError("Previous Pages data could not be read; existing deployment was preserved.") from None


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
    package = json.dumps(encrypt(snapshot, password), separators=(",", ":")).encode()
    if len(package) > MAX_PACKAGE_BYTES:
        raise PackageError("Encrypted package exceeds the size limit.")
    # Never delete or publish an unknown directory that may contain private files.
    if output.is_symlink() or (output.exists() and (
            not output.is_dir() or any(p.name not in ASSETS | {PACKAGE_NAME, ".nojekyll"}
                                      or p.is_symlink() or not p.is_file() for p in output.iterdir()))):
        raise PackageError("Output must be a dedicated site directory with no unknown files or symlinks.")
    output.mkdir(parents=True, exist_ok=True)
    for name in sorted(ASSETS):
        _atomic_write(output / name, (ROOT / "web" / name).read_bytes())
    _atomic_write(output / ".nojekyll", b"")
    _atomic_write(output / PACKAGE_NAME, package)
    if seed_output is not None:
        _atomic_write(seed_output, package)


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
    try:
        password = os.environ.get("PAGES_PASSWORD", "")
        password_bytes(password)  # Fail before contacting Anki or writing files.
        previous = []
        if args.seed.exists() and not args.discard_previous:
            previous.append(load_package(args.seed, password))
        if args.previous_url and not args.discard_previous:
            prior = fetch_previous(args.previous_url, password)
            if prior:
                previous.append(prior)
        if args.source == "ankiweb":
            raw = export_ankiweb(os.environ.get("ANKIWEB_HKEY", ""), os.environ.get("ANKIWEB_ENDPOINT") or None,
                                 timezone=args.timezone, query=args.query, allow_empty=args.allow_empty)
            if not args.cached_media_only:
                from anki_media import download_media
                raw["media"] = download_media(raw, os.environ.get("ANKIWEB_HKEY", ""), os.environ.get("ANKIWEB_ENDPOINT") or None)
                raw["media_complete"] = True
        elif args.source == "ankiconnect":
            raw = export_local(api_key=os.environ.get("ANKI_CONNECT_API_KEY"), expected_profile=args.profile,
                               timezone=args.timezone, query=args.query)
        else:
            if not previous:
                raise PackageError("Create an encrypted seed using the local AnkiConnect importer first.")
            raw = restore_source(previous[-1])
        snapshot = prepare_snapshot(raw, previous)
        build_site(snapshot, password, args.output, seed_output=args.seed_output)
        print("Encrypted Pages site built. No plaintext collection or credentials were published.")
        return 0
    except (PackageError, ConnectorError, SnapshotValidationError, OSError, ValueError):
        print("Pages build failed. Check configuration, password, source and size limits; existing deployment was preserved.", file=sys.stderr)
        return 1
    except Exception:
        print("Pages build failed; private diagnostics were not logged.", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
