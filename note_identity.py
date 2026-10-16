"""Stable identity of the original Anki note text, before display sanitization."""
import hashlib
import json


def note_fingerprint(model: str, fields: dict[str, str]) -> str:
    clear = json.dumps([model, sorted(fields.items())], ensure_ascii=False,
                       separators=(',', ':')).encode('utf-8')
    return hashlib.sha256(clear).hexdigest()
