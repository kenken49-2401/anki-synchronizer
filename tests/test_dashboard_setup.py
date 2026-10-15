import importlib.util
from pathlib import Path
import re
import stat
import subprocess
import sys

from cryptography.fernet import Fernet
import pytest


SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "dashboard_setup.py"
SECRET_NAMES = ("DASHBOARD_PASSWORD", "ANKI_UPLOAD_TOKEN", "DASHBOARD_ENCRYPTION_KEY")


def run_setup(directory, *args):
    return subprocess.run(
        [sys.executable, str(SCRIPT), *map(str, args)],
        cwd=directory, capture_output=True, text=True, check=False,
    )


def read_values(path):
    return dict(line.split("=", 1) for line in path.read_text().splitlines())


def test_default_credentials_are_private_valid_and_never_printed(tmp_path):
    result = run_setup(tmp_path)
    assert result.returncode == 0
    path = tmp_path / ".dashboard.env"
    assert stat.S_IMODE(path.stat().st_mode) == 0o600
    values = read_values(path)
    assert set(values) == {*SECRET_NAMES, "DASHBOARD_DATA_DIR", "TZ"}
    assert len(values["DASHBOARD_PASSWORD"]) >= 12
    assert len(values["ANKI_UPLOAD_TOKEN"]) >= 32
    Fernet(values["DASHBOARD_ENCRYPTION_KEY"].encode("ascii"))
    assert values["DASHBOARD_DATA_DIR"] == ".dashboard-data"
    assert values["TZ"] == "Asia/Tokyo"
    assert all(re.fullmatch(r"[A-Za-z0-9_./=\-]+", value) for value in values.values())
    for name in SECRET_NAMES:
        assert values[name] not in result.stdout + result.stderr
    assert "local editor" in result.stdout
    assert ".dashboard.env" in result.stdout
    assert result.stderr == ""


def test_each_file_has_independent_random_credentials(tmp_path):
    paths = [tmp_path / "first.env", tmp_path / "second.env"]
    for path in paths:
        assert run_setup(tmp_path, "--output", path).returncode == 0
    first, second = map(read_values, paths)
    assert all(first[name] != second[name] for name in SECRET_NAMES)


@pytest.mark.parametrize("existing_kind", ["file", "symlink", "dangling_symlink"])
def test_existing_files_and_symlinks_are_never_overwritten(tmp_path, existing_kind):
    output = tmp_path / "private.env"
    target = tmp_path / "target.env"
    original = "existing-private-content"
    if existing_kind == "file":
        output.write_text(original)
        output.chmod(0o640)
    else:
        if existing_kind == "symlink":
            target.write_text(original)
        output.symlink_to(target)
    before = output.lstat()
    result = run_setup(tmp_path, "--output", output)
    assert result.returncode == 1
    assert "Refusing to overwrite" in result.stderr
    assert original not in result.stdout + result.stderr
    assert output.lstat().st_ino == before.st_ino
    assert output.lstat().st_mode == before.st_mode
    if existing_kind == "dangling_symlink":
        assert output.is_symlink() and not target.exists()
    else:
        assert output.read_text() == original


def test_file_can_be_sourced_in_bash(tmp_path):
    assert run_setup(tmp_path).returncode == 0
    check_environment = (
        "import os; from cryptography.fernet import Fernet; "
        'assert len(os.environ["DASHBOARD_PASSWORD"]) >= 12; '
        'assert len(os.environ["ANKI_UPLOAD_TOKEN"]) >= 32; '
        'Fernet(os.environ["DASHBOARD_ENCRYPTION_KEY"].encode()); '
        'assert os.environ["TZ"] == "Asia/Tokyo"'
    )
    result = subprocess.run(
        ["bash", "-c", 'set -a; source "$1"; exec "$2" -c "$3"',
         "bash", str(tmp_path / ".dashboard.env"), sys.executable, check_environment],
        capture_output=True, text=True, check=False,
    )
    assert result.returncode == 0
    assert result.stdout == result.stderr == ""


def test_errors_do_not_print_exception_payloads(tmp_path, monkeypatch, capsys):
    spec = importlib.util.spec_from_file_location("dashboard_setup", SCRIPT)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    private_value = "private-value-that-must-not-be-printed"

    def fail(*args, **kwargs):
        raise OSError(private_value)

    monkeypatch.setattr(module, "create_env_file", fail)
    assert module.main(["--output", str(tmp_path / "private.env")]) == 1
    output = capsys.readouterr()
    assert private_value not in output.out + output.err
    assert "Could not create" in output.err


def test_missing_output_directory_fails_without_creating_a_file(tmp_path):
    output = tmp_path / "missing" / "private.env"
    result = run_setup(tmp_path, "--output", output)
    assert result.returncode == 1
    assert result.stdout == ""
    assert "Could not create" in result.stderr
    assert not output.exists()


def test_generation_without_fchmod_does_not_print_secrets(tmp_path, monkeypatch, capsys):
    spec = importlib.util.spec_from_file_location("dashboard_setup_without_fchmod", SCRIPT)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    monkeypatch.delattr(module.os, "fchmod", raising=False)
    path = tmp_path / "private.env"
    assert module.main(["--output", str(path)]) == 0
    values = read_values(path)
    Fernet(values["DASHBOARD_ENCRYPTION_KEY"].encode("ascii"))
    assert len(values["DASHBOARD_PASSWORD"]) >= 12
    assert len(values["ANKI_UPLOAD_TOKEN"]) >= 32
    output = capsys.readouterr()
    assert output.err == ""
    for name in SECRET_NAMES:
        assert values[name] not in output.out + output.err
