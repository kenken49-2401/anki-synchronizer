"""Exercise the real Anki sync protocol against Anki's local official server."""
import os
import socket
import subprocess
import sys
import time
import uuid

from anki.collection import Collection
from anki import sync_pb2
from cryptography.fernet import Fernet
import pytest

from engine import Engine
from storage import StorageError
from test_system import Remote


def test_full_download_normal_sync_and_review_history(tmp_path, monkeypatch):
    sock = socket.socket()
    sock.bind(("127.0.0.1", 0))
    port = sock.getsockname()[1]
    sock.close()
    endpoint = f"http://127.0.0.1:{port}/"
    monkeypatch.setenv("NO_PROXY", os.environ.get("NO_PROXY", "") + ",localhost,127.0.0.1")
    env = os.environ.copy()
    env.update(SYNC_HOST="127.0.0.1", SYNC_PORT=str(port), SYNC_BASE=str(tmp_path / "sync-server"),
               SYNC_USER1="test-user:test-password")
    server = subprocess.Popen([sys.executable, "-m", "anki.syncserver"], env=env,
                              stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    seed = None
    try:
        for _ in range(100):
            try:
                with socket.create_connection(("127.0.0.1", port), timeout=.1): break
            except OSError:
                if server.poll() is not None: raise RuntimeError("Local Anki sync server failed")
                time.sleep(.03)
        seed = Collection(str(tmp_path / "seed.anki2"))
        note = seed.new_note(seed.models.by_name("Basic"))
        note["Front"] = "Local sync question"
        note["Back"] = "Local sync answer"
        seed.add_note(note, seed.decks.id("Study"))
        auth = seed.sync_login("test-user", "test-password", endpoint)
        result = seed.sync_collection(auth, sync_media=False)
        assert result.required in (result.FULL_UPLOAD, result.FULL_SYNC)
        seed.close_for_full_sync()
        seed._backend.full_upload_or_download(sync_pb2.FullUploadOrDownloadRequest(auth=auth, upload=True))
        seed.reopen(after_full_sync=True)
        remote = Remote()
        key = Fernet.generate_key().decode()
        engine = Engine(remote, key, ankiweb_hkey=auth.hkey, ankiweb_endpoint=endpoint)
        assert engine.sync(str(uuid.uuid4()))["synced"]
        assert engine.search("")["notes"][0]["fields"]["Back"] == "Local sync answer"
        review = engine.next_review("Study", str(uuid.uuid4()))
        engine.reveal(review["review_token"])
        engine.answer(review["review_token"], "good", str(uuid.uuid4()))
        restarted = Engine(remote, key, ankiweb_hkey=auth.hkey, ankiweb_endpoint=endpoint)
        request_id = str(uuid.uuid4())
        remote.fail_commit = True
        with pytest.raises(StorageError):
            restarted.sync(request_id)
        remote.fail_commit = False
        assert restarted.sync(request_id)["synced"]
        seed.sync_collection(auth, sync_media=False)
        assert seed.db.scalar("select count(*) from revlog") == 1
        assert seed.get_card(review["card_id"]).reps == 1
    finally:
        if seed:
            seed.close()
        server.terminate()
        server.wait(timeout=5)
