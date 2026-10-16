"""Generate the only secret needed for an encrypted static Pages dashboard."""
from __future__ import annotations
import argparse
import os
from pathlib import Path
import secrets
import sys


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, default=Path(".pages.env"))
    args = parser.parse_args(argv)
    try:
        fd = os.open(args.output, os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_NOFOLLOW", 0), 0o600)
        with os.fdopen(fd, "w") as handle:
            handle.write("PAGES_PASSWORD=" + secrets.token_urlsafe(32) + "\nANKI_TIMEZONE=Asia/Tokyo\n")
    except Exception:
        print("Could not create the private file. Existing files are never overwritten.", file=sys.stderr)
        return 1
    print("Private configuration created. Open it locally to read PAGES_PASSWORD; never commit or paste it into chat.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
