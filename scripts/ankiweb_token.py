"""Run on your own computer. Password stays local; writes token to a private file."""
import getpass
import os
import tempfile
from pathlib import Path

from anki.collection import Collection


def main():
    username = input("AnkiWeb email: ").strip()
    password = getpass.getpass("AnkiWeb password (hidden): ")
    with tempfile.TemporaryDirectory() as directory:
        col = Collection(directory + "/collection.anki2")
        try:
            auth = col.sync_login(username, password, None)
        except Exception:
            raise SystemExit("AnkiWeb login failed. No password/token was printed.") from None
        finally:
            col.close()
    path = Path("secrets.env")
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(fd, "w") as output:
        output.write(f"ANKIWEB_HKEY={auth.hkey}\nANKIWEB_ENDPOINT={auth.endpoint}\n")
    print("Saved to secrets.env (owner-only permissions on Unix). Copy into Render's environment settings, then remove the local file.")


if __name__ == "__main__":
    main()
