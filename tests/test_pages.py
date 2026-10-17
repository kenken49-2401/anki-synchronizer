import base64
import json
import shutil
import subprocess

import pytest

import pages_crypto
import pages_site
from pages_crypto import PackageError, decrypt, encrypt
from test_dashboard import snapshot

PASSWORD = "test-only-very-long-pages-password"
PNG = base64.b64decode("iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/x8AAwMCAO+jf4sAAAAASUVORK5CYII=")


def with_image():
    raw = snapshot()
    raw["cards"][0]["front"] = 'PRIVATE_CARD_f128ce H<sub>2</sub>O<img src="molecule.png">'
    raw["media"] = {"molecule.png": {"mime": "image/png", "data": base64.b64encode(PNG).decode()}}
    return raw


def test_package_randomized_authenticated_and_no_plaintext():
    clear = {"private": "PRIVATE_VALUE_7824"}
    one, two = encrypt(clear, PASSWORD), encrypt(clear, PASSWORD)
    assert one["salt"] != two["salt"] and one["iv"] != two["iv"]
    assert decrypt(one, PASSWORD) == clear
    assert "PRIVATE_VALUE_7824" not in json.dumps(one)
    with pytest.raises(PackageError):
        decrypt(one, "different-long-test-password")
    tampered = dict(one)
    data = bytearray(base64.b64decode(one["ciphertext"]))
    data[0] ^= 1
    tampered["ciphertext"] = base64.b64encode(data).decode()
    with pytest.raises(PackageError):
        decrypt(tampered, PASSWORD)


@pytest.mark.parametrize("field,value", [("version", 2), ("iterations", 1), ("iterations", 10**12), ("kdf", "other"), ("salt", "AA=="), ("iv", "not base64"), ("ciphertext", "")])
def test_bad_crypto_parameters_rejected(field, value):
    package = encrypt({}, PASSWORD)
    package[field] = value
    with pytest.raises(PackageError):
        decrypt(package, PASSWORD)


def test_site_contains_only_public_assets_and_ciphertext(tmp_path):
    data = pages_site.prepare_snapshot(with_image())
    site = tmp_path / "site"
    seed = tmp_path / "pages-data" / pages_site.PACKAGE_NAME
    pages_site.build_site(data, PASSWORD, site, seed_output=seed)
    assert {p.name for p in site.iterdir()} == pages_site.ASSETS | {".nojekyll", pages_site.PACKAGE_NAME, pages_site.BUILD_FILE}
    for path in site.iterdir():
        contents = path.read_bytes()
        assert b"PRIVATE_CARD_f128ce" not in contents
        assert PASSWORD.encode() not in contents
        assert base64.b64encode(PNG) not in contents
    assert pages_site.load_package(seed, PASSWORD) == data
    assert (site / pages_site.PACKAGE_NAME).read_bytes() == seed.read_bytes()
    before = seed.read_bytes()
    pages_site.build_site(data, PASSWORD, site)
    assert (site / pages_site.PACKAGE_NAME).read_bytes() != before


def test_build_version_covers_code_not_private_data_and_busts_module_caches(tmp_path, monkeypatch):
    data = pages_site.prepare_snapshot(with_image())
    site = tmp_path / "site"
    pages_site.build_site(data, PASSWORD, site)
    one = json.loads((site / pages_site.BUILD_FILE).read_text())["version"]
    assert len(one) == 64
    assert f'content="{one}"' in (site / 'index.html').read_text()
    assert f'./app.js?v={one}' in (site / 'index.html').read_text()
    assert f'./vault.mjs?v={one}' in (site / 'app.js').read_text()
    data['cards'][0]['tags'].append('private-tag-not-public')
    pages_site.build_site(data, PASSWORD, site)
    assert json.loads((site / pages_site.BUILD_FILE).read_text())["version"] == one
    source = tmp_path / 'source'
    shutil.copytree(pages_site.ROOT / 'web', source / 'web')
    (source / 'web' / 'app.js').write_text((source / 'web' / 'app.js').read_text() + '\n// new code\n')
    monkeypatch.setattr(pages_site, 'ROOT', source)
    pages_site.build_site(data, PASSWORD, site)
    assert json.loads((site / pages_site.BUILD_FILE).read_text())["version"] != one
    manifest = json.loads((site / 'manifest.webmanifest').read_text())
    assert manifest['start_url'] == './' and manifest['display'] == 'standalone'
    assert (site / 'icon-180.png').read_bytes().startswith(b'\x89PNG\r\n\x1a\n')


def test_seed_rebuild_and_image_retention(tmp_path):
    original = pages_site.prepare_snapshot(with_image())
    raw = snapshot()
    raw["cards"][0]["front"] = 'H<sub>2</sub>O<img src="molecule.png">'
    later = pages_site.prepare_snapshot(raw, [original])
    assert later["media"] == original["media"]
    assert "./api/media/" in later["cards"][0]["front_html"]
    rebuilt = pages_site.prepare_snapshot(pages_site.restore_source(later))
    assert rebuilt["media"] == later["media"]
    assert rebuilt["cards"][0]["front_html"] == later["cards"][0]["front_html"]
    assert rebuilt["cards"][0]["fields"] == later["cards"][0]["fields"]
    assert rebuilt["reviews"] == later["reviews"]
    assert rebuilt["cards"][0]["back"].startswith(later["cards"][0]["back"])
    raw["media_complete"] = True
    missing = pages_site.prepare_snapshot(raw, [original])
    assert "media" not in missing
    assert "画像未取得" in missing["cards"][0]["front_html"]


def test_unknown_output_and_symlink_refused(tmp_path):
    site = tmp_path / "site"
    site.mkdir()
    private = site / "secret.env"
    private.write_text("private")
    with pytest.raises(PackageError):
        pages_site.build_site({}, PASSWORD, site)
    assert private.read_text() == "private"
    private.unlink()
    (site / "index.html").symlink_to(tmp_path / "outside")
    with pytest.raises(PackageError):
        pages_site.build_site({}, PASSWORD, site)
    assert not (tmp_path / "outside").exists()


def test_cli_missing_password_or_failed_download_never_builds(tmp_path, monkeypatch, capsys):
    monkeypatch.delenv("PAGES_PASSWORD", raising=False)
    called = []
    monkeypatch.setattr(pages_site, "export_ankiweb", lambda *a, **k: called.append(True))
    assert pages_site.main(["--output", str(tmp_path / "site")]) == 1
    assert not called and not (tmp_path / "site").exists()
    monkeypatch.setenv("PAGES_PASSWORD", PASSWORD)
    def failed(*a, **k):
        raise RuntimeError(PASSWORD + " PRIVATE_CARD")
    monkeypatch.setattr(pages_site, "export_ankiweb", failed)
    assert pages_site.main(["--output", str(tmp_path / "site")]) == 1
    captured = capsys.readouterr()
    assert PASSWORD not in captured.out + captured.err
    assert "PRIVATE_CARD" not in captured.out + captured.err


def test_local_cli_seed_then_offline_rebuild(tmp_path, monkeypatch):
    monkeypatch.setenv("PAGES_PASSWORD", PASSWORD)
    monkeypatch.setattr(pages_site, "export_local", lambda **k: with_image())
    seed = tmp_path / "pages-data" / "snapshot.enc.json"
    assert pages_site.main(["--source", "ankiconnect", "--seed", str(seed), "--seed-output", str(seed), "--output", str(tmp_path / "first")]) == 0
    assert pages_site.main(["--source", "seed", "--seed", str(seed), "--output", str(tmp_path / "second")]) == 0
    assert pages_site.load_package(tmp_path / "second" / "snapshot.enc.json", PASSWORD)["media"]


def test_explicit_password_rotation_ignores_old_ciphertext(tmp_path, monkeypatch):
    seed = tmp_path / "snapshot.enc.json"
    seed.write_text(json.dumps(encrypt({}, "old-test-only-password-1234567")))
    monkeypatch.setenv("PAGES_PASSWORD", PASSWORD)
    monkeypatch.setattr(pages_site, "export_local", lambda **k: with_image())
    def no_fetch(*a, **k):
        raise AssertionError("Do not read old deployment during explicit rotation")
    monkeypatch.setattr(pages_site, "fetch_previous", no_fetch)
    assert pages_site.main(["--source", "ankiconnect", "--seed", str(seed), "--discard-previous",
                            "--previous-url", "https://example.github.io/repo", "--output", str(tmp_path / "site")]) == 0
    assert pages_site.load_package(tmp_path / "site" / "snapshot.enc.json", PASSWORD)["cards"]


def test_previous_fetch_sends_no_secret_and_requires_valid_ciphertext(monkeypatch):
    import httpx
    request_log = []
    package = encrypt({"cards": []}, PASSWORD)
    def serve(request):
        request_log.append(request)
        assert request.method == "GET" and not request.content
        assert "authorization" not in request.headers
        assert PASSWORD not in str(request.url) + str(request.headers)
        return httpx.Response(200, json=package)
    original = httpx.Client
    monkeypatch.setattr(pages_site.httpx, "Client", lambda **k: original(transport=httpx.MockTransport(serve), **k))
    assert pages_site.fetch_previous("https://example.github.io/repo", PASSWORD) == {"cards": []}
    with pytest.raises(PackageError):
        pages_site.fetch_previous("https://example.github.io/repo", "wrong-but-long-enough-password")
    for bad in ("http://example.github.io/", "https://user@evil.example/", "https://example.github.io/?token=secret"):
        with pytest.raises(PackageError):
            pages_site.fetch_previous(bad, PASSWORD)
    assert len(request_log) == 2


def test_workflow_publishes_ciphertext_only_and_never_uses_render():
    import yaml
    workflow = yaml.safe_load((pages_site.ROOT / ".github/workflows/ankiweb-refresh.yml").read_text())
    assert "pull_request" not in workflow["on"]
    assert workflow["on"]["schedule"][0]["cron"] == "17 * * * *"
    build = workflow["jobs"]["build"]
    assert "ANKI_AUTO_SYNC_ENABLED" in build["if"]
    steps = build["steps"]
    command = next(step for step in steps if "pages_site.py" in step.get("run", ""))
    queue = next(step for step in steps if "github_tag_queue.py" in step.get("run", ""))
    assert steps.index(queue) < steps.index(command)
    assert "inputs.source != 'seed'" in queue["if"]
    assert build["permissions"]["issues"] == "write"
    assert "GITHUB_TOKEN" not in command["env"]
    assert "pages_site.py" in command["run"]
    assert "ANKI_UPLOAD_TOKEN" not in command["env"] and "DASHBOARD_URL" not in command["env"]
    upload = next(step for step in steps if step.get("uses", "").startswith("actions/upload-pages-artifact"))
    assert upload["with"]["path"] == "site"
    assert workflow["jobs"]["deploy"]["needs"] == "build"
    assert not (pages_site.ROOT / ".github/workflows/pages-demo.yml").exists()


def test_python_to_browser_webcrypto_compatibility():
    if not shutil.which("node"):
        pytest.skip("Node is needed for Web Crypto interoperability")
    data = pages_site.prepare_snapshot(with_image())
    request = {"package": encrypt(data, PASSWORD), "password": PASSWORD}
    script = """
    import {importPassword,decryptPackage,createMediaURLs,revokeMediaURLs} from './web/vault.mjs';
    let text='';for await(const chunk of process.stdin)text+=chunk;
    const input=JSON.parse(text),key=await importPassword(input.password);
    const data=await decryptPackage(input.package,key),urls=await createMediaURLs(data);
    if(data.cards.length!==1||urls.size!==1||!data.cards[0].front_html.includes('<sub>'))process.exit(1);
    revokeMediaURLs(urls);if(urls.size!==0)process.exit(1);
    """
    result = subprocess.run(["node", "--input-type=module", "-e", script], input=json.dumps(request),
                            text=True, capture_output=True, cwd=pages_site.ROOT, timeout=30)
    assert result.returncode == 0, result.stderr


def test_pages_setup_is_private_and_exclusive(tmp_path, capsys):
    from scripts.pages_setup import main
    path = tmp_path / ".pages.env"
    assert main(["--output", str(path)]) == 0
    data = path.read_text()
    password = data.splitlines()[0].split("=", 1)[1]
    assert len(password) >= 32
    assert path.stat().st_mode & 0o777 == 0o600
    assert password not in capsys.readouterr().out
    assert main(["--output", str(path)]) == 1
    assert path.read_text() == data


def test_note_identity_survives_html_sanitization_and_seed_rebuild():
    from note_identity import note_fingerprint
    raw = with_image()
    raw['cards'][0]['fields']['Back'] = '<b>答え</b><img src="molecule.png">'
    data = pages_site.prepare_snapshot(raw)
    c = data['cards'][0]
    assert c['tag_identity'] == note_fingerprint(raw['cards'][0]['model'], raw['cards'][0]['fields'])
    assert c['tag_identity'] != note_fingerprint(c['model'], c['fields'])
    rebuilt = pages_site.prepare_snapshot(pages_site.restore_source(data))
    assert rebuilt['cards'][0]['tag_identity'] == c['tag_identity']


def test_browser_encrypted_tags_are_importable_by_python(tmp_path, monkeypatch):
    if not shutil.which('node'):
        pytest.skip('Node is needed for Web Crypto interoperability')
    import tag_import
    from test_tag_import import FakeAnki, package
    data = package()
    script = '''
      import {readFileSync} from 'node:fs';
      import {encryptData,importPassword} from './web/vault.mjs';
      const input=JSON.parse(readFileSync(0,'utf8'));
      process.stdout.write(JSON.stringify(await encryptData(input.data,await importPassword(input.password))));
    '''
    result = subprocess.run(['node', '--input-type=module', '-e', script],
                            input=json.dumps({'data': data, 'password': PASSWORD}), text=True,
                            capture_output=True, check=True, cwd=pages_site.ROOT)
    assert '日本語::復習' not in result.stdout and PASSWORD not in result.stdout
    path = tmp_path / 'anki-tag-changes.enc.json'
    path.write_text(result.stdout)
    fake = FakeAnki()
    monkeypatch.setattr(tag_import, 'AnkiConnect', lambda *args: fake)
    outcome = tag_import.import_tag_changes(path, PASSWORD, 'Main', apply=True, sync=True)
    assert outcome['applied'] and outcome['synced']
    assert set(fake.notes[1]['tags']) == {'existing', '日本語::復習', 'new'}


def test_safe_actions_diagnostic_never_contains_exception_content(monkeypatch, capsys):
    monkeypatch.setenv('GITHUB_ACTIONS', 'true')
    try:
        try:
            raise AttributeError('PRIVATE_CARD ::error:: secret-token-123')
        except AttributeError:
            raise RuntimeError('https://example.test/?hkey=secret-token-123') from None
    except RuntimeError as exc:
        pages_site.report_failure('downloading and reading AnkiWeb collection', exc)
    result = capsys.readouterr()
    text = result.out + result.err
    assert '::error title=Anki Pages diagnostic::' in text
    assert 'AttributeError' in text
    assert 'PRIVATE_CARD' not in text
    assert 'secret-token-123' not in text
    assert 'https://' not in text
