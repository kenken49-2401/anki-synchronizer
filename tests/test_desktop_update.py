"""The updater must preserve local files and activate only complete installations."""
import errno
import io
import os
import json
from pathlib import Path
import stat
import tempfile
import unittest
from unittest.mock import patch
import zipfile

from scripts import desktop as app

OLD = "a" * 40
NEW = "b" * 40


def project(path):
    path.mkdir(parents=True, exist_ok=True)
    for name in app.ESSENTIAL:
        item = path / name
        item.parent.mkdir(parents=True, exist_ok=True)
        item.write_text("source")
    (path / ".venv").mkdir(exist_ok=True)


def archive(extra=None):
    output = io.BytesIO()
    with zipfile.ZipFile(output, "w") as z:
        for name in app.ESSENTIAL:
            z.writestr(f"anki-synchronizer-{NEW}/{name}", "new source")
        for name, value in (extra or []):
            z.writestr(name, value)
    return output.getvalue()


class DesktopUpdateTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.root = Path(self.directory.name)
        self.runtime = self.root / ".atlas-runtime"
        self.previous = self.runtime / "versions" / OLD
        project(self.previous)
        app.activate(self.runtime, OLD)

    def create_symlink(self, link, target, *, directory=False):
        try:
            link.symlink_to(target, target_is_directory=directory)
        except OSError as error:
            if os.name == "nt" and (getattr(error, "winerror", None) == 1314 or error.errno in {errno.EACCES, errno.EPERM}):
                self.skipTest("Windows account lacks symbolic link creation privilege")
            raise

    def test_unchanged_version_does_not_download_or_sync(self):
        with patch.object(app, "latest_version", return_value=OLD), patch.object(app, "fetch") as fetch, patch.object(app, "sync_project") as sync:
            self.assertEqual(app.ensure_current(self.root), self.previous)
        fetch.assert_not_called()
        sync.assert_not_called()

    def test_commit_pinned_update_and_private_files_preserved(self):
        for name in (".pages.env", "secrets.env", "site/local", "pages-data/local", ".venv/local", "pages_site.py"):
            target = self.root / name
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text("private original")
        def sync(path):
            self.assertEqual(json.loads((self.runtime / "current.json").read_text())["version"], OLD)
            (path / ".venv").mkdir()
        with patch.object(app, "latest_version", return_value=NEW), patch.object(app, "fetch", return_value=archive()) as fetch, patch.object(app, "sync_project", side_effect=sync):
            active = app.ensure_current(self.root)
        self.assertEqual(active.name, NEW)
        fetch.assert_called_once_with(f"https://codeload.github.com/{app.REPOSITORY}/zip/{NEW}", app.MAX_DOWNLOAD)
        self.assertEqual(app.installed_project(self.runtime), active)
        for name in (".pages.env", "secrets.env", "site/local", "pages-data/local", ".venv/local", "pages_site.py"):
            self.assertEqual((self.root / name).read_text(), "private original")

    def test_failed_dependencies_preserve_previous_pointer(self):
        with patch.object(app, "latest_version", return_value=NEW), patch.object(app, "fetch", return_value=archive()), patch.object(app, "sync_project", side_effect=app.UpdateError("Dependency installation failed")):
            self.assertEqual(app.ensure_current(self.root), self.previous)
        self.assertEqual(app.installed_project(self.runtime), self.previous)
        self.assertFalse((self.runtime / "versions" / NEW).exists())

    def test_corrupt_archive_keeps_previous_working_version(self):
        with patch.object(app, "latest_version", return_value=NEW), patch.object(app, "fetch", return_value=b"invalid zip"), patch.object(app, "sync_project") as sync:
            self.assertEqual(app.ensure_current(self.root), self.previous)
        sync.assert_not_called()
        self.assertFalse((self.runtime / "versions" / NEW).exists())
        self.assertFalse(list(self.runtime.glob("staging-*")))

    def test_offline_uses_previous_without_disclosing_error(self):
        with patch.object(app, "latest_version", side_effect=OSError("secret-value")), patch("builtins.print") as output:
            self.assertEqual(app.ensure_current(self.root), self.previous)
        self.assertNotIn("secret-value", str(output.call_args_list))

    def test_lock_does_not_allow_parallel_installation(self):
        with app.update_lock(self.runtime), patch.object(app, "latest_version") as latest:
            self.assertEqual(app.ensure_current(self.root), self.previous)
        latest.assert_not_called()

    def test_rejects_traversal_and_windows_paths(self):
        for name in (f"anki-synchronizer-{NEW}/../escape.py", f"anki-synchronizer-{NEW}/web/CON.js", f"anki-synchronizer-{NEW}/web/a\\b.js", "/absolute.py"):
            with self.subTest(name=name), self.assertRaises(app.UpdateError):
                app.extract_source(archive([(name, "bad")]), self.root / "extract", NEW)

    def test_rejects_symlink_and_expansion_bomb(self):
        entry = zipfile.ZipInfo(f"anki-synchronizer-{NEW}/web/link.js")
        entry.external_attr = (stat.S_IFLNK | 0o777) << 16
        with self.assertRaises(app.UpdateError):
            app.extract_source(archive([(entry, "../../secrets.env")]), self.root / "extract", NEW)
        with patch.object(app, "MAX_EXPANDED", 2), self.assertRaises(app.UpdateError):
            app.extract_source(archive(), self.root / "extract", NEW)

    def test_secret_files_are_excluded(self):
        destination = self.root / "extract"
        destination.mkdir()
        app.extract_source(archive([(f"anki-synchronizer-{NEW}/secrets.env", "secret"), (f"anki-synchronizer-{NEW}/web/.private/key.json", "secret"), (f"anki-synchronizer-{NEW}/web/manifest.webmanifest", "{}")]), destination, NEW)
        self.assertFalse((destination / "secrets.env").exists())
        self.assertFalse((destination / "web/.private").exists())
        self.assertEqual((destination / "web/manifest.webmanifest").read_text(), "{}")

    def test_command_uses_absolute_env_file_without_secret_values(self):
        with patch.object(app.subprocess, "call", return_value=0) as call:
            app.run_script(self.root, self.previous, "tag_import.py", ["export.enc.json", "--profile", "Main"], env_file=True)
        command = call.call_args.args[0]
        self.assertEqual(command[command.index("--env-file") + 1], str(self.root / ".pages.env"))
        self.assertEqual(call.call_args.kwargs["cwd"], self.root)
        self.assertEqual(call.call_args.kwargs["env"]["UV_PROJECT_ENVIRONMENT"], str(self.previous / ".venv"))

    def test_runtime_symlinks_cannot_redirect_updates(self):
        outside = self.root / "outside"
        outside.mkdir()
        (outside / "keep").write_text("private")
        other_root = self.root / "other"
        other_root.mkdir()
        self.create_symlink(other_root / ".atlas-runtime", outside, directory=True)
        with patch.object(app, "latest_version") as latest, self.assertRaises(app.UpdateError):
            app.ensure_current(other_root)
        latest.assert_not_called()
        self.assertEqual((outside / "keep").read_text(), "private")
        self.create_symlink(self.runtime / "versions" / NEW, outside, directory=True)
        with patch.object(app, "latest_version", return_value=NEW), patch.object(app, "fetch") as fetch:
            self.assertEqual(app.ensure_current(self.root), self.previous)
        fetch.assert_not_called()
        self.assertEqual((outside / "keep").read_text(), "private")

    def test_static_server_does_not_follow_links_outside_site(self):
        site = self.root / "site"
        site.mkdir()
        secret = self.root / "secrets.env"
        secret.write_text("private")
        self.create_symlink(site / "leak.env", secret)
        handler = object.__new__(app.SiteHandler)
        handler.directory = str(site)
        self.assertEqual(Path(handler.translate_path("/leak.env")).resolve(), (site / ".not-found").resolve())
        self.assertEqual(handler.translate_path("/index.html"), str(site / "index.html"))

    def test_local_command_keeps_stable_browser_origin(self):
        with patch.object(app, "ensure_current", return_value=self.previous), patch.object(app, "run_script", return_value=0), patch.object(app.http.server, "ThreadingHTTPServer") as server, patch.object(app.webbrowser, "open") as browser:
            instance = server.return_value.__enter__.return_value
            instance.server_port = app.LOCAL_PORT
            instance.serve_forever.side_effect = KeyboardInterrupt
            self.assertEqual(app.main(["--command", "local"]), 0)
        self.assertEqual(server.call_args.args[0], ("127.0.0.1", 8766))
        browser.assert_called_once_with("http://127.0.0.1:8766/")

    def test_occupied_local_port_fails_without_fallback_origin(self):
        with patch.object(app, "ensure_current", return_value=self.previous), patch.object(app, "run_script", return_value=0), patch.object(app.http.server, "ThreadingHTTPServer", side_effect=OSError("Address already in use")) as server, patch.object(app.webbrowser, "open") as browser:
            self.assertEqual(app.main(["--command", "local"]), 1)
        server.assert_called_once()
        self.assertEqual(server.call_args.args[0], ("127.0.0.1", 8766))
        browser.assert_not_called()

    def test_lock_symlink_is_preserved_without_following_it(self):
        secret = self.root / "secrets.env"
        secret.write_text("private")
        lock = self.runtime / "update.lock"
        self.create_symlink(lock, secret)
        with self.assertRaises(app.UpdateError):
            with app.update_lock(self.runtime):
                self.fail("symlink lock must not be acquired")
        self.assertTrue(lock.is_symlink())
        self.assertEqual(secret.read_text(), "private")

    def test_setup_resumes_when_pages_configuration_already_exists(self):
        private = self.root / ".pages.env"
        private.write_text("private-pages")
        with patch.object(app, "run_script", return_value=0) as run:
            self.assertEqual(app.setup_local(self.root, self.previous), 0)
        run.assert_called_once_with(self.root, self.previous, "scripts/ankiweb_token.py", [])
        self.assertEqual(private.read_text(), "private-pages")

    def test_setup_resumes_when_token_configuration_already_exists(self):
        private = self.root / "secrets.env"
        private.write_text("private-token")
        with patch.object(app, "run_script", return_value=0) as run:
            self.assertEqual(app.setup_local(self.root, self.previous), 0)
        run.assert_called_once_with(self.root, self.previous, "scripts/pages_setup.py", [])
        self.assertEqual(private.read_text(), "private-token")

    def test_complete_setup_never_reads_or_rewrites_secrets(self):
        for name in (".pages.env", "secrets.env"):
            (self.root / name).write_text("private-value")
        with patch.object(app, "run_script") as run, patch.object(Path, "read_text", side_effect=AssertionError("must not read secrets")), patch("builtins.print") as output:
            self.assertEqual(app.setup_local(self.root, self.previous), 0)
        run.assert_not_called()
        self.assertNotIn("private-value", str(output.call_args_list))

    def test_setup_runs_missing_steps_in_order_and_stops_on_failure(self):
        with patch.object(app, "run_script", return_value=0) as run:
            self.assertEqual(app.setup_local(self.root, self.previous), 0)
        self.assertEqual([call.args[2] for call in run.call_args_list], ["scripts/pages_setup.py", "scripts/ankiweb_token.py"])
        with patch.object(app, "run_script", return_value=7) as run:
            self.assertEqual(app.setup_local(self.root, self.previous), 7)
        run.assert_called_once()

    def test_setup_rejects_nonregular_paths_before_creating_any_files(self):
        for kind in ("directory", "symlink", "dangling-symlink"):
            with self.subTest(kind=kind):
                target = self.root / "secrets.env"
                if kind == "directory":
                    target.mkdir()
                elif kind == "symlink":
                    self.create_symlink(target, self.previous / "pages_site.py")
                else:
                    self.create_symlink(target, self.root / "missing-private")
                with patch.object(app, "run_script") as run, self.assertRaises(app.UpdateError):
                    app.setup_local(self.root, self.previous)
                run.assert_not_called()
                if target.is_symlink():
                    target.unlink()
                else:
                    target.rmdir()

    def test_windows_junctions_cannot_redirect_runtime_or_secret_paths(self):
        for path in (self.runtime, self.runtime / "versions", self.runtime / "bundled"):
            with self.subTest(path=path), patch.object(Path, "is_junction", autospec=True, side_effect=lambda candidate: candidate == path), self.assertRaises(app.UpdateError):
                app.safe_runtime(self.runtime)
        private = self.root / "secrets.env"
        with patch.object(Path, "is_junction", autospec=True, side_effect=lambda candidate: candidate == private), patch.object(app, "run_script") as run, self.assertRaises(app.UpdateError):
            app.setup_local(self.root, self.previous)
        run.assert_not_called()
        lock = self.runtime / "update.lock"
        with patch.object(Path, "is_junction", autospec=True, side_effect=lambda candidate: candidate == lock), self.assertRaises(app.UpdateError):
            with app.update_lock(self.runtime):
                self.fail("must not acquire a junction lock")

    def test_windows_junction_output_path_stops_local_command(self):
        output = Path(app.__file__).resolve().parent.parent / "site"
        with patch.object(Path, "is_junction", autospec=True, side_effect=lambda candidate: candidate == output), patch.object(app, "ensure_current", return_value=self.previous), patch.object(app, "run_script") as run:
            self.assertEqual(app.main(["--command", "local"]), 1)
        run.assert_not_called()

    def test_offline_first_launch_uses_isolated_bundled_copy(self):
        (self.runtime / "current.json").unlink()
        project(self.root)
        (self.root / ".venv" / "keep").write_text("original")
        with patch.object(app, "latest_version", side_effect=OSError()), patch.object(app, "sync_project", side_effect=lambda path: (path / ".venv").mkdir()):
            active = app.ensure_current(self.root)
        self.assertEqual(active, self.runtime / "bundled")
        self.assertEqual((self.root / ".venv" / "keep").read_text(), "original")


if __name__ == "__main__":
    unittest.main()
