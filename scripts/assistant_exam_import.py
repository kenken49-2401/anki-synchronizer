"""Merge an encrypted assistant-prepared exam package into encrypted Study Atlas data."""
from __future__ import annotations
import base64
import json
import math
import os
import sys
import uuid
from pathlib import Path

import httpx

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from pages_crypto import decrypt, encrypt, password_bytes

MAX_BYTES = 1024 * 1024
PATH = "/repos/kenken49-2401/anki-synchronizer/contents/study-data/study.enc.json"
BRANCH = "prototype/study-data"


def number(value):
    return isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(value)


def check_exam(record):
    if not isinstance(record, dict) or not isinstance(record.get("sourceKey"), str) or len(record["sourceKey"]) > 300:
        raise ValueError("Invalid import record.")
    if any(not isinstance(record.get(k), str) or len(record[k]) > 200 for k in ("name", "subject", "date", "kind")):
        raise ValueError("Invalid import record.")
    if not number(record.get("score")) or not number(record.get("max")) or record["max"] <= 0 or not 0 <= record["score"] <= record["max"]:
        raise ValueError("Invalid import record.")
    questions = record.get("questions")
    if not isinstance(questions, list) or not 0 < len(questions) <= 30:
        raise ValueError("Invalid import record.")
    for q in questions:
        if not isinstance(q, dict) or not isinstance(q.get("name"), str) or not number(q.get("max")) or q["max"] <= 0:
            raise ValueError("Invalid import record.")
        for field in ("score", "average", "selfscore", "feeling"):
            value = q.get(field)
            if value is not None and (not number(value) or not 0 <= value <= q["max"]):
                raise ValueError("Invalid import record.")
        if not isinstance(q.get("tags"), list) or any(not isinstance(tag, str) for tag in q["tags"]):
            raise ValueError("Invalid import record.")


def merge(current, payload):
    if not isinstance(current, dict) or current.get("schema_version") != 1 or any(not isinstance(current.get(k), list) for k in ("studies", "scores", "tasks")):
        raise ValueError("Invalid existing data.")
    if not isinstance(payload, dict) or payload.get("format") != "study-atlas-exams-v1" or not isinstance(payload.get("scores"), list) or len(payload["scores"]) > 500:
        raise ValueError("Invalid import package.")
    additions = []
    for item in payload["scores"]:
        check_exam(item)
        if any(isinstance(x, dict) and (x.get("sourceKey") == item["sourceKey"] or
               (x.get("name") == item["name"] and x.get("subject") == item["subject"] and x.get("kind") == item["kind"]))
               for x in current["scores"] + additions):
            continue
        additions.append({**item, "id": str(uuid.uuid4())})
    return {**current, "scores": current["scores"] + additions}, len(additions)


def run():
    repo = os.environ.get("GITHUB_REPOSITORY", "")
    token = os.environ.get("GITHUB_TOKEN", "")
    password = os.environ.get("STUDY_ATLAS_PASSWORD", "")
    inbox_key = os.environ.get("ASSISTANT_IMPORT_KEY", "")
    if repo != "kenken49-2401/anki-synchronizer" or not token:
        raise ValueError("Repository or token is not configured.")
    password_bytes(password)
    password_bytes(inbox_key)
    payload = decrypt(json.loads(Path("assistant-import/exams.enc.json").read_bytes()), inbox_key)
    with httpx.Client(base_url="https://api.github.com", headers={"Authorization": "Bearer " + token,
                      "Accept": "application/vnd.github+json", "X-GitHub-Api-Version": "2022-11-28"},
                      follow_redirects=False, timeout=60) as client:
        response = client.get(PATH, params={"ref": BRANCH})
        response.raise_for_status()
        result = response.json()
        if result.get("type") != "file" or result.get("encoding") != "base64" or not isinstance(result.get("sha"), str):
            raise ValueError("Existing data is unavailable.")
        raw = base64.b64decode("".join(result["content"].split()), validate=True)
        if len(raw) > MAX_BYTES:
            raise ValueError("Existing data exceeds limit.")
        current = decrypt(json.loads(raw), password)
        updated, count = merge(current, payload)
        if not count:
            print("No new records to import.")
            return
        encrypted = json.dumps(encrypt(updated, password), separators=(",", ":")).encode()
        if len(encrypted) > MAX_BYTES:
            raise ValueError("Encrypted result exceeds limit.")
        response = client.put(PATH, json={"message": "Import encrypted study records", "branch": BRANCH,
                              "sha": result["sha"], "content": base64.b64encode(encrypted).decode("ascii")})
        response.raise_for_status()
        print(f"Imported {count} encrypted records.")


if __name__ == "__main__":
    try:
        run()
    except Exception:
        print("Import failed. Existing data was not intentionally replaced; verify secrets, permissions, and any concurrent update.", file=sys.stderr)
        raise SystemExit(1) from None
