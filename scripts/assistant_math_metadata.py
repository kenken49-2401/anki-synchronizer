"""Add encrypted math problem metadata to the existing encrypted Study Atlas snapshot."""
from __future__ import annotations
import base64
import copy
import json
import os
import sys
from pathlib import Path
import httpx
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from pages_crypto import decrypt, encrypt, password_bytes
from scripts.assistant_exam_import import PATH, BRANCH, MAX_BYTES


def merge_metadata(current, payload):
    if not isinstance(current, dict) or current.get("schema_version") != 1 or not isinstance(current.get("scores"), list):
        raise ValueError("Invalid existing data.")
    if not isinstance(payload, dict) or payload.get("format") != "study-atlas-math-metadata-v1" or not isinstance(payload.get("items"), list) or len(payload["items"]) > 100:
        raise ValueError("Invalid metadata.")
    updated = copy.deepcopy(current)
    changed = 0
    for item in payload["items"]:
        if not isinstance(item, dict) or not isinstance(item.get("year"), str) or not item["year"].isdigit() or len(item["year"]) != 4:
            raise ValueError("Invalid metadata.")
        levels, times = item.get("difficulty"), item.get("expectedMinutes")
        if (not isinstance(levels, list) or not isinstance(times, list) or len(levels) != 6 or len(times) != 6 or
            any(v not in ("A", "B", "C", "D", None) for v in levels) or
            any(v is not None and (type(v) is not int or v < 0 or v % 5) for v in times)):
            raise ValueError("Invalid metadata.")
        # Prefer the exact imported source. Only fall back to a unique exact year label.
        source = "sheet:1N_L6U1kVEnrhIFVL3CoTmXRwWSbv3yhH1xtlmWsZPdY:数学:" + item["year"] + ":数学"
        candidates = [x for x in updated["scores"] if isinstance(x, dict) and x.get("subject") == "数学" and x.get("sourceKey") == source]
        if not candidates:
            candidates = [x for x in updated["scores"] if isinstance(x, dict) and x.get("subject") == "数学" and x.get("name") == item["year"]]
        if len(candidates) != 1:
            continue
        questions = candidates[0].get("questions")
        if not isinstance(questions, list):
            continue
        for index in range(6):
            matches = [q for q in questions if isinstance(q, dict) and q.get("name") == str(index + 1)]
            if len(matches) != 1:
                continue
            question = matches[0]
            for field, value in (("difficulty", levels[index]), ("expectedMinutes", times[index])):
                if value is not None and question.get(field) is None:
                    question[field] = value
                    changed += 1
    return updated, changed


def run():
    if os.environ.get("GITHUB_REPOSITORY") != "kenken49-2401/anki-synchronizer" or not os.environ.get("GITHUB_TOKEN"):
        raise ValueError("Invalid repository configuration.")
    password = os.environ.get("STUDY_ATLAS_PASSWORD", "")
    import_key = os.environ.get("ASSISTANT_IMPORT_KEY", "")
    password_bytes(password)
    password_bytes(import_key)
    payload = decrypt(json.loads(Path("assistant-import/math-metadata.enc.json").read_bytes()), import_key)
    headers = {"Authorization": "Bearer " + os.environ["GITHUB_TOKEN"], "Accept": "application/vnd.github+json",
               "X-GitHub-Api-Version": "2022-11-28"}
    with httpx.Client(base_url="https://api.github.com", headers=headers, follow_redirects=False, timeout=60) as client:
        response = client.get(PATH, params={"ref": BRANCH})
        response.raise_for_status()
        result = response.json()
        if result.get("type") != "file" or result.get("encoding") != "base64" or not isinstance(result.get("sha"), str):
            raise ValueError("Existing data is unavailable.")
        raw = base64.b64decode("".join(result["content"].split()), validate=True)
        if len(raw) > MAX_BYTES:
            raise ValueError("Existing data exceeds limit.")
        updated, count = merge_metadata(decrypt(json.loads(raw), password), payload)
        if not count:
            print("No missing metadata to add.")
            return
        encrypted = json.dumps(encrypt(updated, password), separators=(",", ":")).encode()
        if len(encrypted) > MAX_BYTES:
            raise ValueError("Encrypted result exceeds limit.")
        response = client.put(PATH, json={"message":"Add encrypted math metadata", "branch":BRANCH,
                               "sha":result["sha"], "content":base64.b64encode(encrypted).decode("ascii")})
        response.raise_for_status()
        print(f"Added {count} missing metadata values.")


if __name__ == "__main__":
    try:
        run()
    except Exception:
        print("Metadata import failed; check secrets, permissions, and concurrent changes.", file=sys.stderr)
        raise SystemExit(1) from None
