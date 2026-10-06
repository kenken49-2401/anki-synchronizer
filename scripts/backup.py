"""Download an encrypted backup using local environment variables; no live mutation."""
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from storage import Supabase


def main():
    db = Supabase(os.environ["SUPABASE_URL"], os.environ["SUPABASE_SERVICE_KEY"])
    rows = db.request("GET", "/anki_state", params={"id": "eq.1", "select": "revision,payload"})
    if not rows or not rows[0]["payload"]:
        raise SystemExit("No saved collection yet.")
    row = rows[0]
    output_path = Path(f"anki-backup-{row['revision']}.encrypted")
    fd = os.open(output_path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(fd, "w") as output:
        output.write(row["payload"])
    print(f"Saved encrypted backup: {output_path}. Keep DATA_ENCRYPTION_KEY separately.")


if __name__ == "__main__":
    main()
