import asyncio
import copy
import os
import threading
import socket
import time
import uuid
from types import SimpleNamespace
from unittest.mock import patch

import httpx
import httpx2
import pytest
import uvicorn
from cryptography.fernet import Fernet
from fastmcp import Client
from fastmcp.client.transports import StreamableHttpTransport
from fastmcp.server.auth import AccessToken
from fastmcp.server.auth.providers.jwt import StaticTokenVerifier
from key_value.aio.stores.memory import MemoryStore
from anki import sync_pb2

from engine import Engine, UserError, plain
from storage import StorageError, EncryptedOAuthStore, Supabase

os.environ["ANKI_FACTORY_ONLY"] = "1"
from server import create_server, require_owner, OwnerGitHubProvider


class Remote:
    """Models durable state shared by otherwise independent engine instances."""
    def __init__(self):
        self.payload = None
        self.revision = 0
        self.lease = None
        self.fail_commit = False

    def acquire(self, lease):
        if self.lease:
            raise StorageError("busy")
        self.lease = lease
        return {"payload": self.payload, "revision": self.revision}

    def commit(self, lease, revision, payload):
        if self.fail_commit or self.lease != lease or revision != self.revision:
            raise StorageError("commit failed")
        self.payload = payload
        self.revision += 1
        self.lease = None
        return self.revision

    def release(self, lease):
        if self.lease == lease:
            self.lease = None


@pytest.fixture
def setup():
    remote = Remote()
    key = Fernet.generate_key().decode()
    return remote, key, Engine(remote, key)


def rid():
    return str(uuid.uuid4())


def add(engine, question="What is 2+2?", request_id=None):
    return engine.add("Study", "Basic", {"Front": question, "Back": "4"}, ["math"], request_id or rid())


def test_restart_search_edit_delete(setup):
    remote, key, engine = setup
    created = add(engine)
    assert "What is 2+2?" not in remote.payload
    restarted = Engine(remote, key)
    found = restarted.search("tag:math")["notes"][0]
    assert found["note_id"] == created["note_id"]
    changed = restarted.edit(found["note_id"], found["version"], {"Back": "four"}, None, rid())
    assert changed["tags"] == ["math"]
    assert changed["fields"]["Back"] == "four"
    with pytest.raises(UserError, match="変更"):
        restarted.edit(found["note_id"], found["version"], {"Back": "wrong"}, None, rid())
    restarted.delete(changed["note_id"], changed["version"], rid())
    assert restarted.search("")["total"] == 0


def test_add_and_answer_idempotency(setup):
    remote, key, engine = setup
    request = rid()
    first = add(engine, request_id=request)
    assert add(Engine(remote, key), request_id=request) == first
    assert engine.describe()["cards"] == 1
    next_card = engine.next_review("Study", rid())
    assert "answer" not in next_card
    assert next_card["question"] == "What is 2+2?"
    token = next_card["review_token"]
    with pytest.raises(UserError, match="reveal_answer"):
        engine.answer(token, "good", rid())
    assert "4" in Engine(remote, key).reveal(token)["answer"]
    request = rid()
    answer = engine.answer(token, "good", request)
    assert Engine(remote, key).answer(token, "good", request) == answer
    count = engine.run(lambda col, _: col.db.scalar("select count(*) from revlog"))
    assert count == 1
    with pytest.raises(UserError, match="異なる操作"):
        engine.answer(token, "again", request)


def test_duplicate_notes_rejected(setup):
    _, _, engine = setup
    add(engine)
    with pytest.raises(UserError, match="重複"):
        add(engine)


def test_failed_commit_never_reports_success_or_loses_old_state(setup):
    remote, key, engine = setup
    add(engine)
    before = remote.payload
    request = rid()
    remote.fail_commit = True
    with pytest.raises(StorageError):
        add(engine, "Another question", request)
    assert remote.payload == before
    remote.fail_commit = False
    assert add(Engine(remote, key), "Another question", request)
    assert engine.describe()["cards"] == 2


def test_wrong_key_never_initializes_empty_collection(setup):
    remote, _, engine = setup
    add(engine)
    before = remote.payload
    with pytest.raises(UserError, match="復号"):
        Engine(remote, Fernet.generate_key().decode()).describe()
    assert before == remote.payload


def test_snapshot_size_limit(setup):
    remote, key, engine = setup
    add(engine)
    before = remote.payload
    with pytest.raises(UserError, match="上限"):
        Engine(remote, key, max_bytes=100).describe()
    assert remote.payload == before


def test_review_invalidated_by_edit(setup):
    _, _, engine = setup
    note = add(engine)
    review = engine.next_review("Study", rid())
    engine.edit(note["note_id"], note["version"], {"Back": "new answer"}, None, rid())
    with pytest.raises(UserError, match="セッション"):
        engine.reveal(review["review_token"])


def test_rendered_html_never_executes_or_fetches_external_content():
    assert plain('<style>.card{x:y}</style><script>steal()</script>hello<br>world') == "hello\nworld"


def test_owner_allowlist():
    require_owner(SimpleNamespace(claims={"sub": "42"}), "42")
    for token in (None, SimpleNamespace(claims={"sub": "43"}), SimpleNamespace(claims={"login": "42"})):
        with pytest.raises(UserError):
            require_owner(token, "42")


def test_mcp_tools_end_to_end(setup):
    _, _, engine = setup
    auth = StaticTokenVerifier(tokens={
        "owner": {"client_id": "test", "scopes": ["read:user"], "sub": "42"},
        "other": {"client_id": "test", "scopes": ["read:user"], "sub": "43"},
    })
    mcp, app = create_server({"ALLOWED_GITHUB_USER_ID": "42", "PUBLIC_URL": "https://example.onrender.com"},
                             test_engine=engine, test_auth=auth)
    sock = socket.socket()
    sock.bind(("127.0.0.1", 0))
    port = sock.getsockname()[1]
    web = uvicorn.Server(uvicorn.Config(app, log_level="critical", access_log=False))
    thread = threading.Thread(target=lambda: web.run(sockets=[sock]), daemon=True)
    thread.start()
    for _ in range(100):
        if web.started:
            break
        time.sleep(0.02)
    assert web.started
    def transport(token):
        return StreamableHttpTransport(f"http://127.0.0.1:{port}/mcp", auth=token,
            httpx_client_factory=lambda **kwargs: httpx2.AsyncClient(trust_env=False, **kwargs))
    async def scenario():
        async with Client(transport("owner")) as client:
            tools = await client.list_tools()
            assert len(tools) == 9
            result = await client.call_tool("add_note", {"deck": "Study", "note_type": "Basic",
                "fields": {"Front": "Capital of Japan?", "Back": "Tokyo"}, "tags": [], "request_id": rid()})
            assert result.data["fields"]["Back"] == "Tokyo"
            question = (await client.call_tool("next_review", {"deck": "Study", "request_id": rid()})).data
            token = question["review_token"]
            await client.call_tool("reveal_answer", {"review_token": token})
            recorded = await client.call_tool("record_answer", {"review_token": token, "rating": "good", "request_id": rid()})
            assert recorded.data["recorded"]
        async with Client(transport("other")) as client:
            with pytest.raises(Exception):
                await client.call_tool("describe_collection", {})
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="https://example.onrender.com") as client:
            assert (await client.get("/health")).status_code == 200
            assert (await client.post("/mcp", json={})).status_code == 401
            assert (await client.post("/mcp", content=b"x" * 65537)).status_code == 413
            assert (await client.get("/health", headers={"Host": "evil.example"})).status_code == 400
    try:
        asyncio.run(asyncio.wait_for(scenario(), timeout=20))
    finally:
        web.should_exit = True
        thread.join(timeout=5)
        sock.close()


def test_sync_stops_before_destructive_full_replace(setup):
    remote, key, engine = setup
    add(engine)
    engine.hkey = "fake-test-token"
    with patch("anki.collection.Collection.sync_collection", return_value=sync_pb2.SyncCollectionResponse(required=2)), \
         patch("anki._backend.RustBackend.full_upload_or_download") as full:
        result = engine.sync(rid())
        assert not result["synced"] and result["full_sync_required"]
        full.assert_not_called()
    with pytest.raises(UserError, match="明示"):
        engine.sync(rid(), "upload")
    assert Engine(remote, key).describe()["cards"] == 1


def test_owner_oauth_rejects_valid_token_for_other_account():
    auth = OwnerGitHubProvider(owner_id="42", client_id="test", client_secret="test-secret",
        base_url="https://example.onrender.com", client_storage=MemoryStore())
    from fastmcp.server.auth.oauth_proxy import OAuthProxy
    async def scenario():
        with patch.object(OAuthProxy, "load_access_token", return_value=AccessToken(
                token="test", client_id="test", scopes=[], claims={"sub": "43"})):
            assert await auth.verify_token("test") is None
        with patch.object(OAuthProxy, "load_access_token", return_value=AccessToken(
                token="test", client_id="test", scopes=[], claims={"sub": "42"})):
            assert await auth.verify_token("test") is not None
    asyncio.run(scenario())


def test_invalid_production_config_fails_closed():
    for env in ({}, {"ALLOWED_GITHUB_USER_ID": "some-uuid"},
                {"ALLOWED_GITHUB_USER_ID": "42", "PUBLIC_URL": "http://example.com"}):
        with pytest.raises(ValueError):
            create_server(env)


def test_oauth_tokens_encrypted_and_restored_after_restart():
    class FakeRest:
        def __init__(self): self.rows = {}
        async def arequest(self, method, path, **kwargs):
            if method == "POST":
                row = kwargs["json"]
                self.rows[(row["p_collection"], row["p_key"])] = {
                    "payload": row["p_payload"], "created_at": row["p_created_at"], "expires_at": row["p_expires_at"]}
            elif method == "GET":
                params = kwargs["params"]
                row = self.rows.get((params["collection"][3:], params["key"][3:]))
                return [row] if row else []
    async def scenario():
        db = FakeRest()
        key = Fernet.generate_key().decode()
        store = EncryptedOAuthStore(db, key)
        await store.put("test-key", {"access_token": "secret-token"}, collection="tokens", ttl=3600)
        assert "secret-token" not in str(db.rows)
        restarted = EncryptedOAuthStore(db, key)
        assert (await restarted.get("test-key", collection="tokens"))["access_token"] == "secret-token"
    asyncio.run(scenario())
