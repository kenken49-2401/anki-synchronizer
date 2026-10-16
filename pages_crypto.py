"""Authenticated, password-encrypted Pages packages compatible with Web Crypto."""
from __future__ import annotations

import base64
import json
import os
from typing import Any

from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from cryptography.hazmat.primitives.kdf.pbkdf2 import PBKDF2HMAC

FORMAT = "anki-atlas-encrypted"
ITERATIONS = 600_000
AAD = b"Anki Atlas snapshot v1"
MAX_CLEAR_BYTES = 32 * 1024 * 1024
MAX_PACKAGE_BYTES = 45 * 1024 * 1024


class PackageError(ValueError):
    """Safe errors never contain passwords or card data."""


def password_bytes(password: str) -> bytes:
    try:
        encoded = password.encode("utf-8")
        if not 16 <= len(encoded) <= 1024:
            raise ValueError
        return encoded
    except (AttributeError, UnicodeError, ValueError):
        raise PackageError("PAGES_PASSWORD must contain 16 to 1024 UTF-8 bytes; use a long random password.") from None


def _key(password: str, salt: bytes) -> bytes:
    return PBKDF2HMAC(algorithm=hashes.SHA256(), length=32, salt=salt, iterations=ITERATIONS).derive(password_bytes(password))


def _b64(value: bytes) -> str:
    return base64.b64encode(value).decode("ascii")


def _decode(value: Any, *, size: int | None = None) -> bytes:
    try:
        if not isinstance(value, str) or len(value) > MAX_PACKAGE_BYTES:
            raise ValueError
        decoded = base64.b64decode(value, validate=True)
        if size is not None and len(decoded) != size:
            raise ValueError
        return decoded
    except (ValueError, UnicodeError):
        raise PackageError("Invalid encrypted package.") from None


def encrypt(snapshot: dict[str, Any], password: str) -> dict[str, Any]:
    password_bytes(password)
    try:
        clear = json.dumps(snapshot, ensure_ascii=False, allow_nan=False, separators=(",", ":")).encode("utf-8")
    except (ValueError, UnicodeError, TypeError):
        raise PackageError("Snapshot cannot be encoded.") from None
    if len(clear) > MAX_CLEAR_BYTES:
        raise PackageError("Snapshot exceeds 32 MiB.")
    salt, iv = os.urandom(16), os.urandom(12)
    encrypted = AESGCM(_key(password, salt)).encrypt(iv, clear, AAD)
    return {"format": FORMAT, "version": 1, "kdf": "PBKDF2-SHA256", "iterations": ITERATIONS,
            "salt": _b64(salt), "iv": _b64(iv), "ciphertext": _b64(encrypted)}


def decrypt(package: Any, password: str) -> dict[str, Any]:
    if (not isinstance(package, dict) or package.get("format") != FORMAT
            or type(package.get("version")) is not int or package["version"] != 1
            or package.get("kdf") != "PBKDF2-SHA256"
            or type(package.get("iterations")) is not int or package["iterations"] != ITERATIONS):
        raise PackageError("Unsupported encrypted package.")
    salt, iv = _decode(package.get("salt"), size=16), _decode(package.get("iv"), size=12)
    encrypted = _decode(package.get("ciphertext"))
    if not 16 <= len(encrypted) <= MAX_CLEAR_BYTES + 16:
        raise PackageError("Invalid encrypted package size.")
    key = _key(password, salt)
    try:
        clear = AESGCM(key).decrypt(iv, encrypted, AAD)
        result = json.loads(clear)
        if not isinstance(result, dict):
            raise ValueError
        return result
    except Exception:
        raise PackageError("Cannot decrypt the package; check the password and file integrity.") from None
