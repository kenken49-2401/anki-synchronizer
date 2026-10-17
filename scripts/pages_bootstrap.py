"""Publish the interface before credentials exist; never replace encrypted data."""
from pathlib import Path
import sys

import httpx

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from pages_site import write_public_assets


def bootstrap(base_url: str, output: Path) -> None:
    if output.exists() or output.is_symlink():
        raise ValueError("Bootstrap requires a new output directory.")
    # Only a real 404 allows first-time publication. Denials and network errors stop it.
    with httpx.Client(timeout=60, follow_redirects=False) as client:
        with client.stream("GET", base_url.rstrip("/") + "/snapshot.enc.json") as response:
            if response.status_code != 404:
                raise ValueError("Bootstrap stopped: data exists or deployment status is unknown.")
    write_public_assets(output, setup_pending=True)


if __name__ == "__main__":
    bootstrap(sys.argv[1], Path("site"))
