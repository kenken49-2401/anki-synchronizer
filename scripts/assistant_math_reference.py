"""Merge encrypted year-specific math reference values into Study Atlas data."""
from __future__ import annotations
import base64, copy, json, math, os, sys
from pathlib import Path
import httpx
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from pages_crypto import decrypt, encrypt, password_bytes
from scripts.assistant_exam_import import PATH, BRANCH, MAX_BYTES

def merge_reference(current, payload):
    if not isinstance(current, dict) or current.get("schema_version") != 1 or not isinstance(current.get("scores"), list):
        raise ValueError("Invalid current data.")
    if not isinstance(payload, dict) or payload.get("format") != "study-atlas-math-reference-v1" or not isinstance(payload.get("items"), list) or len(payload["items"]) > 150:
        raise ValueError("Invalid reference data.")
    updated = copy.deepcopy(current)
    reference = updated.setdefault("mathReference", {})
    if not isinstance(reference, dict):
        raise ValueError("Invalid existing reference data.")
    count = 0
    for item in payload["items"]:
        if not isinstance(item, dict) or not isinstance(item.get("year"), str) or len(item["year"]) != 4 or not item["year"].isdigit():
            raise ValueError("Invalid year.")
        questions = item.get("questions")
        if not isinstance(questions, list) or len(questions) != 6:
            raise ValueError("Invalid questions.")
        for q in questions:
            if not isinstance(q, dict) or q.get("difficulty") not in (None, "A", "B", "C", "D") or q.get("status") not in (None, "new", "done", "review"):
                raise ValueError("Invalid difficulty.")
            for field in ("minutes", "expectedMinutes"):
                v = q.get(field)
                if v is not None and (type(v) not in (int,float) or not math.isfinite(v) or v < 0 or (field == "expectedMinutes" and v % 5)):
                    raise ValueError("Invalid time.")
        year = item["year"]
        if year not in reference:
            reference[year] = copy.deepcopy(questions)
            count += 1
        elif isinstance(reference[year], list) and len(reference[year]) == 6:
            changed = False
            for target, incoming in zip(reference[year], questions):
                if isinstance(target, dict) and "status" not in target and incoming.get("status") is not None:
                    target["status"] = incoming["status"]
                    changed = True
            if changed:
                count += 1
    return updated, count

def run():
    if os.environ.get("GITHUB_REPOSITORY") != "kenken49-2401/anki-synchronizer" or not os.environ.get("GITHUB_TOKEN"):
        raise ValueError("Invalid configuration.")
    password, key = os.environ.get("STUDY_ATLAS_PASSWORD", ""), os.environ.get("ASSISTANT_IMPORT_KEY", "")
    password_bytes(password)
    password_bytes(key)
    payload = decrypt(json.loads(Path("assistant-import/math-reference.enc.json").read_bytes()), key)
    headers={"Authorization":"Bearer "+os.environ["GITHUB_TOKEN"],"Accept":"application/vnd.github+json","X-GitHub-Api-Version":"2022-11-28"}
    with httpx.Client(base_url="https://api.github.com",headers=headers,follow_redirects=False,timeout=60) as client:
        response=client.get(PATH,params={"ref":BRANCH})
        response.raise_for_status()
        result=response.json()
        if result.get("type")!="file" or result.get("encoding")!="base64" or not isinstance(result.get("sha"),str):
            raise ValueError("Existing data unavailable.")
        raw=base64.b64decode("".join(result["content"].split()),validate=True)
        if len(raw)>MAX_BYTES: raise ValueError("Data exceeds limit.")
        updated,count=merge_reference(decrypt(json.loads(raw),password),payload)
        if not count:
            print("No new reference years to add.")
            return
        encrypted=json.dumps(encrypt(updated,password),separators=(",",":")).encode()
        if len(encrypted)>MAX_BYTES: raise ValueError("Encrypted result exceeds limit.")
        response=client.put(PATH,json={"message":"Add encrypted math reference","branch":BRANCH,"sha":result["sha"],"content":base64.b64encode(encrypted).decode("ascii")})
        response.raise_for_status()
        print(f"Added {count} reference years.")

if __name__=="__main__":
    try: run()
    except Exception:
        print("Reference import failed; check secrets, permissions and concurrent changes.",file=sys.stderr)
        raise SystemExit(1) from None
