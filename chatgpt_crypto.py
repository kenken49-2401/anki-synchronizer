"""Envelope encryption for serverless ChatGPT requests and responses.

This module only handles cryptography; it does not authorize or process requests.
"""
from __future__ import annotations

import base64
import binascii
import json
import os

from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric.x25519 import X25519PrivateKey, X25519PublicKey
from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from cryptography.hazmat.primitives.kdf.hkdf import HKDF

AAD = b"anki-atlas-chatgpt-envelope-v1"
MAX_PLAINTEXT = 32768


class EnvelopeError(ValueError):
    """Generic errors do not expose request data or key material."""


def _encode(data):
    return base64.b64encode(data).decode("ascii")


def _decode(value, length=None):
    if not isinstance(value, str) or len(value) > 50000:
        raise EnvelopeError("Invalid envelope.")
    try:
        result = base64.b64decode(value, validate=True)
    except (ValueError, binascii.Error):
        raise EnvelopeError("Invalid envelope.") from None
    if length is not None and len(result) != length:
        raise EnvelopeError("Invalid envelope.")
    return result


def public_bytes(key):
    return key.public_bytes(serialization.Encoding.Raw, serialization.PublicFormat.Raw)


def new_keypair():
    key = X25519PrivateKey.generate()
    private = key.private_bytes(serialization.Encoding.Raw, serialization.PrivateFormat.Raw, serialization.NoEncryption())
    return _encode(private), _encode(public_bytes(key.public_key()))


def _derive(shared, ephemeral, recipient):
    return HKDF(algorithm=hashes.SHA256(), length=32, salt=None,
                info=AAD + ephemeral + recipient).derive(shared)


def seal(value, recipient_public):
    try:
        clear = json.dumps(value, ensure_ascii=False, allow_nan=False, separators=(",", ":")).encode("utf-8")
        if not isinstance(value, dict) or len(clear) > MAX_PLAINTEXT:
            raise ValueError
        recipient_raw = _decode(recipient_public, 32)
        recipient = X25519PublicKey.from_public_bytes(recipient_raw)
        ephemeral = X25519PrivateKey.generate()
        ephemeral_raw = public_bytes(ephemeral.public_key())
        key = _derive(ephemeral.exchange(recipient), ephemeral_raw, recipient_raw)
        nonce = os.urandom(12)
        ciphertext = AESGCM(key).encrypt(nonce, clear, AAD)
        return {"format": "anki-atlas-chatgpt", "version": 1, "ephemeral": _encode(ephemeral_raw),
                "nonce": _encode(nonce), "ciphertext": _encode(ciphertext)}
    except (ValueError, TypeError, UnicodeError, OverflowError):
        raise EnvelopeError("Invalid envelope input.") from None


def open_envelope(envelope, recipient_private):
    try:
        if (not isinstance(envelope, dict) or set(envelope) != {"format", "version", "ephemeral", "nonce", "ciphertext"}
                or envelope["format"] != "anki-atlas-chatgpt" or type(envelope["version"]) is not int or envelope["version"] != 1):
            raise ValueError
        private = X25519PrivateKey.from_private_bytes(_decode(recipient_private, 32))
        ephemeral_raw = _decode(envelope["ephemeral"], 32)
        nonce = _decode(envelope["nonce"], 12)
        ciphertext = _decode(envelope["ciphertext"])
        if not 16 <= len(ciphertext) <= MAX_PLAINTEXT + 16:
            raise ValueError
        shared = private.exchange(X25519PublicKey.from_public_bytes(ephemeral_raw))
        key = _derive(shared, ephemeral_raw, public_bytes(private.public_key()))
        result = json.loads(AESGCM(key).decrypt(nonce, ciphertext, AAD))
        if not isinstance(result, dict):
            raise ValueError
        return result
    except Exception:
        raise EnvelopeError("Cannot open envelope.") from None
