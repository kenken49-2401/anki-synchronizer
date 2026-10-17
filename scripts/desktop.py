"""Launch the official app, checking main for updates without replacing user files."""
from __future__ import annotations

import argparse
from contextlib import contextmanager
from functools import partial
import http.server
import io
import json
import os
from pathlib import Path, PurePosixPath
import re
import shutil
import stat
import subprocess
import tempfile
import time
import urllib.request
import webbrowser
import zipfile

REPOSITORY = "kenken49-2401/anki-synchronizer"
WEB_URL = "https://kenken49-2401.github.io/anki-synchronizer/"
LOCAL_PORT = 8766
SHA = re.compile(r"[0-9a-f]{40}\Z")
MAX_DOWNLOAD = 32 * 1024 * 1024
MAX_EXPANDED = 96 * 1024 * 1024
MAX_FILES = 3000
ESSENTIAL = ("pyproject.toml", "uv.lock", "pages_site.py", "tag_import.py", "scripts/pages_setup.py", "scripts/ankiweb_token.py", "web/index.html")


class UpdateError(Exception):
    pass


class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        raise UpdateError("Unexpected server redirect")


def fetch(url: str, limit: int) -> bytes:
    request = urllib.request.Request(url, headers={"User-Agent": "Anki-Atlas-Desktop", "Accept": "application/vnd.github+json"})
    with urllib.request.build_opener(NoRedirect).open(request, timeout=20) as response:
        chunks = []
        size = 0
        deadline = time.monotonic() + 40
        while True:
            chunk = response.read1(min(65536, limit + 1 - size))
            if time.monotonic() > deadline:
                raise UpdateError("Download exceeded time limit")
            if not chunk:
                break
            size += len(chunk)
            if size > limit:
                raise UpdateError("Download exceeds size limit")
            chunks.append(chunk)
    return b"".join(chunks)


def latest_version() -> str:
    version = json.loads(fetch(f"https://api.github.com/repos/{REPOSITORY}/commits/main", 1024 * 1024))["sha"]
    if not isinstance(version, str) or not SHA.fullmatch(version):
        raise UpdateError("Invalid version response")
    return version


def allowed_file(path: PurePosixPath) -> bool:
    if any(part.startswith(".") for part in path.parts):
        return False
    if len(path.parts) == 1:
        return path.suffix == ".py" or path.name in {"pyproject.toml", "uv.lock", "LICENSE"}
    if path.parts[0] == "scripts":
        return len(path.parts) == 2 and path.suffix == ".py"
    return path.parts[0] == "web" and path.suffix in {".mjs", ".js", ".html", ".css", ".json", ".svg", ".png", ".webmanifest"}


def extract_source(data: bytes, destination: Path, version: str) -> None:
    if not SHA.fullmatch(version) or len(data) > MAX_DOWNLOAD:
        raise UpdateError("Invalid archive")
    prefix = f"anki-synchronizer-{version}"
    with zipfile.ZipFile(io.BytesIO(data)) as archive:
        entries = archive.infolist()
        if len(entries) > MAX_FILES or sum(item.file_size for item in entries) > MAX_EXPANDED:
            raise UpdateError("Archive exceeds extraction limits")
        selected = []
        seen = set()
        for entry in entries:
            # ZipInfo normalizes backslashes on Windows and truncates NULs.
            # Validate the original name before either transformation hides it.
            name = entry.orig_filename
            path = PurePosixPath(name)
            if ("\\" in name or "\x00" in name or path.is_absolute() or ".." in path.parts
                    or ":" in name or not path.parts or path.parts[0] != prefix
                    or any(part in {"", ".", ".."} for part in name.rstrip("/").split("/"))):
                raise UpdateError("Unsafe archive path")
            mode = entry.external_attr >> 16
            if stat.S_ISLNK(mode) or (stat.S_IFMT(mode) not in (0, stat.S_IFREG, stat.S_IFDIR)):
                raise UpdateError("Unsafe archive entry")
            if entry.flag_bits & 1:
                raise UpdateError("Encrypted archive entry")
            if entry.is_dir():
                continue
            relative = PurePosixPath(*path.parts[1:])
            # Windows normalizes trailing periods/spaces and treats device names specially.
            if any(part.endswith((".", " ")) or re.fullmatch(r"(?i)(con|prn|aux|nul|com[0-9]|lpt[0-9])(?:\..*)?", part) for part in relative.parts):
                raise UpdateError("Unsafe platform path")
            key = str(relative).casefold()
            if key in seen:
                raise UpdateError("Duplicate archive entry")
            seen.add(key)
            if allowed_file(relative):
                selected.append((entry, relative))
        for entry, relative in selected:
            target = destination.joinpath(*relative.parts)
            target.parent.mkdir(parents=True, exist_ok=True)
            with archive.open(entry) as source, target.open("xb") as output:
                shutil.copyfileobj(source, output)
    validate_project(destination)


def is_link(path: Path) -> bool:
    # Directory junctions on Windows can redirect writes just like symbolic links.
    return path.is_symlink() or path.is_junction()


def validate_project(project: Path) -> None:
    for name in ESSENTIAL:
        path = project / name
        if not path.is_file() or is_link(path) or any(is_link(project / parent) for parent in Path(name).parents):
            raise UpdateError("Incomplete application source")


def runtime_environment(project: Path) -> dict[str, str]:
    environment = os.environ.copy()
    environment["UV_PROJECT_ENVIRONMENT"] = str(project / ".venv")
    return environment


def sync_project(project: Path) -> None:
    # Keep dependency diagnostics out of logs: package sources can contain credentials.
    result = subprocess.run(["uv", "sync", "--frozen", "--project", str(project)],
                            cwd=project, env=runtime_environment(project), stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    if result.returncode:
        raise UpdateError("Dependency installation failed")


@contextmanager
def update_lock(runtime: Path):
    lock = runtime / "update.lock"
    if is_link(lock):
        raise UpdateError("Update lock must not be a symbolic link or junction")
    try:
        fd = os.open(lock, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
    except FileExistsError:
        raise UpdateError("Another update is running (if it stopped unexpectedly, remove .atlas-runtime/update.lock)") from None
    try:
        os.close(fd)
        yield
    finally:
        lock.unlink(missing_ok=True)


def safe_runtime(runtime: Path) -> None:
    for path in (runtime, runtime / "versions", runtime / "current.json", runtime / "current.json.tmp", runtime / "bundled", runtime / "bundled-ready"):
        if is_link(path):
            raise UpdateError("Runtime storage must not contain symbolic links or junctions")


def installed_project(runtime: Path) -> Path | None:
    try:
        safe_runtime(runtime)
        version = json.loads((runtime / "current.json").read_text(encoding="utf-8"))["version"]
        if not isinstance(version, str) or not SHA.fullmatch(version):
            return None
        project = runtime / "versions" / version
        if is_link(project):
            return None
        validate_project(project)
        if is_link(project / ".venv") or not (project / ".venv").is_dir():
            return None
        return project
    except (OSError, ValueError, KeyError, TypeError, UpdateError):
        return None


def activate(runtime: Path, version: str) -> None:
    temporary = runtime / "current.json.tmp"
    temporary.write_text(json.dumps({"version": version}) + "\n", encoding="utf-8")
    os.replace(temporary, runtime / "current.json")


def ensure_current(root: Path) -> Path:
    runtime = root / ".atlas-runtime"
    safe_runtime(runtime)
    runtime.mkdir(exist_ok=True, mode=0o700)
    try:
        with update_lock(runtime):
            safe_runtime(runtime)
            previous = installed_project(runtime)
            version = latest_version()
            if previous is not None and previous.name == version:
                print("Anki Atlas is up to date.")
                return previous
            versions = runtime / "versions"
            versions.mkdir(exist_ok=True)
            target = versions / version
            # Never execute an interrupted installation: remove and stage it again.
            if is_link(target):
                raise UpdateError("Runtime storage must not contain symbolic links or junctions")
            if target.exists():
                shutil.rmtree(target)
            stage = Path(tempfile.mkdtemp(prefix="staging-", dir=runtime))
            try:
                data = fetch(f"https://codeload.github.com/{REPOSITORY}/zip/{version}", MAX_DOWNLOAD)
                extract_source(data, stage, version)
                # uv environments contain absolute paths; install at the final location.
                os.replace(stage, target)
                try:
                    sync_project(target)
                except Exception:
                    shutil.rmtree(target, ignore_errors=True)
                    raise
                activate(runtime, version)
                print("Anki Atlas update installed.")
                return target
            finally:
                shutil.rmtree(stage, ignore_errors=True)
    except Exception as error:
        # Exceptions from HTTP/subprocess libraries may include private proxy URLs.
        reason = str(error) if isinstance(error, UpdateError) else "Update service unavailable or invalid response"
        print(f"Update check: {reason}.")
        previous = installed_project(runtime)
        if previous is not None:
            print("Using the previously installed version.")
            return previous
        if isinstance(error, UpdateError) and str(error).startswith("Another update"):
            raise
        print("Preparing the bundled version; latest update could not be confirmed.")
        with update_lock(runtime):
            safe_runtime(runtime)
            bundled = runtime / "bundled"
            ready = runtime / "bundled-ready"
            if ready.is_file():
                validate_project(bundled)
                if not is_link(bundled / ".venv") and (bundled / ".venv").is_dir():
                    return bundled
            if bundled.exists():
                shutil.rmtree(bundled)
            bundled.mkdir()
            for directory, folders, names in os.walk(root, followlinks=False):
                directory = Path(directory)
                folders[:] = [name for name in folders if not name.startswith(".")
                              and not is_link(directory / name)
                              and (directory != root or name in {"scripts", "web"})]
                for name in names:
                    source = directory / name
                    relative = source.relative_to(root)
                    if not is_link(source) and source.is_file() and allowed_file(PurePosixPath(relative.as_posix())):
                        target = bundled / relative
                        target.parent.mkdir(parents=True, exist_ok=True)
                        shutil.copyfile(source, target)
            validate_project(bundled)
            sync_project(bundled)
            ready.touch()
            return bundled


def run_script(root: Path, project: Path, script: str, args: list[str], *, env_file: bool = False) -> int:
    command = ["uv", "run", "--frozen", "--project", str(project)]
    if env_file:
        command += ["--env-file", str(root / ".pages.env")]
    command += ["python", str(project / script), *args]
    return subprocess.call(command, cwd=root, env=runtime_environment(project))


def setup_local(root: Path, project: Path) -> int:
    steps = ((".pages.env", "scripts/pages_setup.py"), ("secrets.env", "scripts/ankiweb_token.py"))
    existing = {}
    # Validate both paths before either setup step can create a file.
    for name, _ in steps:
        if is_link(root / name):
            raise UpdateError("Private configuration paths must be regular files")
        try:
            mode = (root / name).lstat().st_mode
        except FileNotFoundError:
            existing[name] = False
        else:
            if not stat.S_ISREG(mode):
                raise UpdateError("Private configuration paths must be regular files")
            existing[name] = True
    for name, script in steps:
        if existing[name]:
            print(f"Keeping existing {name}.")
            continue
        status = run_script(root, project, script, [])
        if status:
            return status
    print("Private configuration setup is complete.")
    return 0


class SiteHandler(http.server.SimpleHTTPRequestHandler):
    def translate_path(self, path: str) -> str:
        translated = Path(super().translate_path(path))
        base = Path(self.directory).resolve()
        if not translated.resolve().is_relative_to(base):
            return str(base / ".not-found")
        return str(translated)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--command", choices=("open", "setup", "local", "import-tags"), default="open")
    parser.add_argument("arguments", nargs=argparse.REMAINDER)
    args = parser.parse_args(argv)
    extra = args.arguments[1:] if args.arguments[:1] == ["--"] else args.arguments
    root = Path(__file__).resolve().parent.parent
    try:
        if args.command == "open":
            if not webbrowser.open(WEB_URL):
                print(f"Could not open your browser. Open this address manually: {WEB_URL}")
                return 1
            return 0
        project = ensure_current(root)
        if args.command == "setup":
            return setup_local(root, project)
        if args.command == "import-tags":
            return run_script(root, project, "tag_import.py", extra, env_file=True)
        if is_link(root / "site") or is_link(root / "pages-data"):
            raise UpdateError("Local output directories must not be symbolic links or junctions")
        status = run_script(root, project, "pages_site.py", ["--source", "ankiconnect", "--output", str(root / "site"), "--seed-output", str(root / "pages-data" / "snapshot.enc.json"), *extra], env_file=True)
        if status:
            return status
        handler = partial(SiteHandler, directory=str(root / "site"))
        try:
            local_server = http.server.ThreadingHTTPServer(("127.0.0.1", LOCAL_PORT), handler)
        except OSError:
            print(f"Local server could not use port {LOCAL_PORT}. Close the other process, or open the existing app at http://127.0.0.1:{LOCAL_PORT}/ separately.")
            return 1
        with local_server as server:
            webbrowser.open(f"http://127.0.0.1:{server.server_port}/")
            print("Local app running. Press Ctrl+C to close.")
            server.serve_forever()
    except KeyboardInterrupt:
        return 0
    except Exception:
        print("The app could not start. Check uv installation, local configuration, and network access.")
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
