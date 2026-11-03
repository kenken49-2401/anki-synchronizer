"""Publish new UI with the current encrypted Pages data, without contacting Anki."""
from __future__ import annotations

import hashlib
import json
import os
import sys
from pathlib import Path
from urllib.parse import urlsplit

import httpx

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from pages_crypto import MAX_PACKAGE_BYTES, PackageError, decrypt, password_bytes
from pages_site import MAX_MEDIA_PACKAGES, MEDIA_FILE, PACKAGE_NAME, _atomic_write, write_public_assets

MAX_MEDIA_TOTAL = 768 * 1024 * 1024


def download(client: httpx.Client, url: str, limit: int) -> bytes:
    result = bytearray()
    with client.stream("GET", url) as response:
        response.raise_for_status()
        for chunk in response.iter_bytes():
            result.extend(chunk)
            if len(result) > limit:
                raise PackageError("Published encrypted data exceeds its limit.")
    return bytes(result)


def publish(previous_url: str, password: str, output: Path) -> None:
    parsed = urlsplit(previous_url)
    if (parsed.scheme != "https" or not parsed.hostname or parsed.username is not None
            or parsed.password is not None or parsed.query or parsed.fragment):
        raise PackageError("Invalid published Pages URL.")
    password_bytes(password)
    if output.exists() and (output.is_symlink() or not output.is_dir() or any(output.iterdir())):
        raise PackageError("Output must be an empty dedicated directory.")
    with httpx.Client(timeout=60, follow_redirects=False) as client:
        base = previous_url.rstrip("/")
        encrypted = download(client, base + "/" + PACKAGE_NAME, MAX_PACKAGE_BYTES)
        snapshot = decrypt(json.loads(encrypted), password)
        if snapshot.get("schema_version") != 1 or not isinstance(snapshot.get("cards"), list) or not isinstance(snapshot.get("reviews"), list):
            raise PackageError("Published snapshot is invalid.")
        names = snapshot.get("media_packages", [])
        if (not isinstance(names, list) or len(names) > MAX_MEDIA_PACKAGES
                or any(not isinstance(name, str) or not MEDIA_FILE.fullmatch(name) for name in names)
                or len(names) != len(set(names))):
            raise PackageError("Published image manifest is invalid.")
        output.mkdir(parents=True, exist_ok=True)
        total = 0
        for name in names:
            blob = download(client, base + "/" + name, MAX_PACKAGE_BYTES)
            total += len(blob)
            if total > MAX_MEDIA_TOTAL or hashlib.sha256(blob).hexdigest() != name[6:-9]:
                raise PackageError("Published encrypted image is invalid.")
            _atomic_write(output / name, blob)
        _atomic_write(output / PACKAGE_NAME, encrypted)
    write_public_assets(output)


if __name__ == "__main__":
    try:
        publish(os.environ.get("PAGES_PREVIOUS_URL", ""), os.environ.get("PAGES_PASSWORD", ""), Path("site"))
    except Exception:
        print("Study UI publication failed; existing Pages deployment was preserved.", file=sys.stderr)
        raise SystemExit(1) from None
