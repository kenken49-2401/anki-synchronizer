import base64
import io
import json
import os
import socket
import subprocess
import sys
import time
import zipfile
from unittest.mock import patch

from anki import sync_pb2
from anki.collection import Collection
import httpx
import pytest

import anki_media
from cloud_sync import CloudSyncError
from test_pages import PNG


def archive(entries, mapping=None):
    output = io.BytesIO()
    with zipfile.ZipFile(output, "w") as z:
        for name, value in entries.items():
            z.writestr(name, value)
        z.writestr("_meta", json.dumps(mapping if mapping is not None else {"0": "diagram.png"}))
    return output.getvalue()


def test_media_zip_has_no_filesystem_extraction_and_strict_mapping():
    result = anki_media._unzip(archive({"0": PNG}), {"diagram.png"})
    assert base64.b64decode(result["diagram.png"]["data"]) == PNG
    for data in [archive({"../outside": PNG}, {"../outside": "diagram.png"}),
                 archive({"0": PNG}, {"0": "../outside.png"}),
                 archive({"0": b"x" * (2 * 1024 * 1024 + 1)})]:
        with pytest.raises(ValueError):
            anki_media._unzip(data, {"diagram.png"})


def test_image_requests_are_only_begin_and_download_and_no_token_in_url(monkeypatch):
    calls = []
    def serve(request):
        calls.append(request.url.path)
        assert "private-test-token" not in str(request.url)
        assert request.method == "POST"
        if request.url.path == "/msync/begin":
            return httpx.Response(200, json={"data": {"sk": "private-test-session"}, "err": ""})
        assert request.url.path == "/msync/downloadFiles"
        return httpx.Response(200, content=archive({"0": PNG}))
    original = httpx.Client
    monkeypatch.setattr(anki_media.httpx, "Client", lambda **k: original(transport=httpx.MockTransport(serve), **k))
    snapshot = {"cards": [{"front": '<img src="diagram.png"><img src="https://evil.example/x">', "back": ""}]}
    result = anki_media.download_media(snapshot, "private-test-token")
    assert "diagram.png" in result
    assert calls == ["/msync/begin", "/msync/downloadFiles"]


def test_redirect_to_other_host_never_receives_secret(monkeypatch):
    calls = []
    def serve(request):
        calls.append(request.url.host)
        return httpx.Response(307, headers={"Location": "https://evil.example/msync/begin"})
    original = httpx.Client
    monkeypatch.setattr(anki_media.httpx, "Client", lambda **k: original(transport=httpx.MockTransport(serve), **k))
    with pytest.raises(CloudSyncError):
        anki_media.download_media({"cards": [{"front": '<img src="diagram.png">', "back": ""}]}, "private-test-token")
    assert calls == ["sync.ankiweb.net"]


def test_official_server_media_download_never_calls_upload(tmp_path, monkeypatch):
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        port = sock.getsockname()[1]
    endpoint = f"http://127.0.0.1:{port}/"
    monkeypatch.setenv("NO_PROXY", os.environ.get("NO_PROXY", "") + ",localhost,127.0.0.1")
    env = os.environ.copy()
    env.update(SYNC_HOST="127.0.0.1", SYNC_PORT=str(port), SYNC_BASE=str(tmp_path / "remote"), SYNC_USER1="user:password")
    server = subprocess.Popen([sys.executable, "-m", "anki.syncserver"], env=env, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    col = None
    try:
        for _ in range(100):
            try:
                with socket.create_connection(("127.0.0.1", port), timeout=.1):
                    break
            except OSError:
                time.sleep(.03)
        col = Collection(str(tmp_path / "seed.anki2"))
        auth = col.sync_login("user", "password", endpoint)
        # Seed only the test server. The downloader has no upload endpoint.
        name = col.media.write_data("diagram.png", PNG)
        col._backend.sync_media(auth)
        snapshot = {"cards": [{"front": f'<img src="{name}">', "back": ""}]}
        with patch.object(anki_media, "_response", wraps=anki_media._response) as requests:
            first = anki_media.download_media(snapshot, auth.hkey, _test_endpoint=endpoint)
            second = anki_media.download_media(snapshot, auth.hkey, _test_endpoint=endpoint)
        assert first == second
        assert base64.b64decode(first[name]["data"]) == PNG
        assert {call.args[2] for call in requests.call_args_list} == {"begin", "downloadFiles"}
    finally:
        if col:
            col.close()
        server.terminate()
        server.wait(timeout=5)
