import base64, json, os
from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from cryptography.hazmat.primitives.kdf.pbkdf2 import PBKDF2HMAC
from cryptography.hazmat.primitives import hashes

def encrypt_snapshot(snapshot, passphrase):
    salt, nonce = os.urandom(16), os.urandom(12)
    key = PBKDF2HMAC(algorithm=hashes.SHA256(), length=32, salt=salt, iterations=600000).derive(passphrase.encode("utf-8"))
    raw = json.dumps(snapshot, ensure_ascii=False).encode("utf-8")
    ciphertext = AESGCM(key).encrypt(nonce, raw, b"anki-atlas-v1")
    b64 = lambda data: base64.b64encode(data).decode("ascii")
    return {"version": 1, "kdf": "PBKDF2-SHA256", "iterations": 600000, "salt": b64(salt), "nonce": b64(nonce), "ciphertext": b64(ciphertext)}
