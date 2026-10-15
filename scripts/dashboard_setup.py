"""Create private dashboard credentials locally without displaying their values."""

from __future__ import annotations

import argparse
import os
from pathlib import Path
import secrets
import sys

from cryptography.fernet import Fernet


def create_env_file(path: Path) -> None:
    """Exclusively create a shell-compatible dotenv file readable by its owner."""
    values = {
        "DASHBOARD_PASSWORD": secrets.token_urlsafe(24),
        "ANKI_UPLOAD_TOKEN": secrets.token_urlsafe(32),
        "DASHBOARD_ENCRYPTION_KEY": Fernet.generate_key().decode("ascii"),
        "DASHBOARD_DATA_DIR": ".dashboard-data",
        "TZ": "Asia/Tokyo",
    }
    # These generated values use only characters safe in unquoted shell values.
    contents = "".join(f"{name}={value}\n" for name, value in values.items())
    flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_NOFOLLOW", 0)
    descriptor = os.open(path, flags, 0o600)
    with os.fdopen(descriptor, "w", encoding="ascii", newline="\n") as output:
        if hasattr(os, "fchmod"):
            os.fchmod(output.fileno(), 0o600)
        output.write(contents)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, default=Path(".dashboard.env"))
    args = parser.parse_args(argv)
    try:
        create_env_file(args.output)
    except FileExistsError:
        print("Refusing to overwrite an existing output file or symlink.", file=sys.stderr)
        return 1
    except Exception:
        # Exceptions from file operations or secret generation must never reveal
        # credential values or an exception payload containing private data.
        print("Could not create the private environment file; check its directory and permissions.", file=sys.stderr)
        return 1
    print(f"Created {str(args.output)!r}.")
    print("Open this file in your local editor to read DASHBOARD_PASSWORD for browser login.")
    print("Keep the file private, do not commit it, and back up the encryption key securely.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
