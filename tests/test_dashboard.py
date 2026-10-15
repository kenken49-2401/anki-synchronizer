import asyncio
import copy
import json

from cryptography.fernet import Fernet
import httpx
import pytest

from dashboard import DashboardConfig, SESSION_COOKIE, create_dashboard, validate_snapshot


PASSWORD = "correct horse battery staple"
TOKEN = "upload-token-for-tests-" + "x" * 32
ORIGIN = "https://study.example"


@pytest.fixture
def config(tmp_path):
    return DashboardConfig(PASSWORD, TOKEN, Fernet.generate_key().decode(), tmp_path / "private")


def snapshot():
    return {
        "schema_version": 1,
        "source": {"kind": "ankiconnect", "profile": "Japanese", "timezone": "Asia/Tokyo"},
        "synced_at": "2026-10-16T03:00:00Z",
        "cards": [{
            "id": 100, "note_id": 99, "deck": "日本語", "model": "Basic", "tags": ["言語::動詞", "N3"],
            "front": "<style>body{display:none}</style><div>出かける</div><script>alert('secret')</script>",
            "back": "<b>to go out</b><img src=x onerror=alert(1)>",
            "fields": {"Front": "出かける", "Back": "<b>to go out</b>"},
            "reps": 2, "lapses": 1, "interval": -60, "due": 1000, "suspended": False,
        }],
        "reviews": [
            {"id": 1792116000000, "card_id": 100, "ease": 1, "time_ms": 5000, "type": 1},
            {"id": 1792116000001, "card_id": 100, "ease": 3, "time_ms": 7000, "type": 1},
            {"id": 1792116000002, "card_id": 100, "ease": 0, "time_ms": 0, "type": 4},
        ],
    }


def client_for(config):
    return httpx.AsyncClient(transport=httpx.ASGITransport(app=create_dashboard(config)), base_url=ORIGIN)


async def login(client):
    response = await client.post("/api/login", json={"password": PASSWORD}, headers={"Origin": ORIGIN})
    assert response.status_code == 200
    return response


def test_private_api_authentication_csrf_and_secure_session(config):
    async def run():
        async with client_for(config) as client:
            assert (await client.get("/api/health")).json() == {"status": "ok"}
            assert (await client.get("/api/session")).json() == {"authenticated": False, "configured": True}
            response = await client.get("/api/snapshot")
            assert response.status_code == 401
            assert response.headers["cache-control"] == "no-store"
            assert "Access-Control-Allow-Origin" not in response.headers
            for origin in (None, "https://attacker.example", "null"):
                response = await client.post("/api/login", json={"password": PASSWORD}, headers={"Origin": origin} if origin else {})
                assert response.status_code == 403
            response = await login(client)
            cookie = response.headers["set-cookie"].lower()
            assert "httponly" in cookie and "samesite=strict" in cookie and "secure" in cookie
            assert (await client.get("/api/session")).json()["authenticated"] is True
            assert (await client.get("/api/snapshot")).json() == {"snapshot": None}
            assert (await client.post("/api/logout", headers={"Origin": "https://attacker.example"})).status_code == 403
            assert (await client.get("/api/session")).json()["authenticated"] is True
            assert (await client.post("/api/logout", headers={"Origin": ORIGIN})).status_code == 200
            assert (await client.get("/api/snapshot")).status_code == 401
    asyncio.run(run())


def test_upload_token_is_distinct_from_browser_login(config):
    async def run():
        async with client_for(config) as client:
            data = snapshot()
            assert (await client.post("/api/snapshot", json=data)).status_code == 401
            assert (await client.post("/api/snapshot", json=data, headers={"Authorization": "Bearer incorrect"})).status_code == 401
            await login(client)
            assert (await client.post("/api/snapshot", json=data, headers={"Origin": ORIGIN})).status_code == 401
            uploaded = await client.post("/api/snapshot", json=data, headers={"Authorization": f"Bearer {TOKEN}"})
            assert uploaded.status_code == 200
            assert uploaded.json()["cards"] == 1
            assert uploaded.json()["reviews"] == 3
            # Upload credentials never grant read access to private cards.
            client.cookies.clear()
            assert (await client.get("/api/snapshot", headers={"Authorization": f"Bearer {TOKEN}"})).status_code == 401
    asyncio.run(run())


def test_encrypted_atomic_persistence_and_safe_text_after_restart(config):
    async def run():
        async with client_for(config) as client:
            response = await client.post("/api/snapshot", json=snapshot(), headers={"Authorization": f"Bearer {TOKEN}"})
            assert response.status_code == 200
        saved = config.data_dir / "snapshot.fernet"
        raw = saved.read_bytes()
        assert "出かける".encode() not in raw
        assert b"to go out" not in raw and b"cards" not in raw
        assert saved.stat().st_mode & 0o777 == 0o600
        assert not list(config.data_dir.glob(".upload-*"))
        decrypted = json.loads(Fernet(config.encryption_key).decrypt(raw))
        assert decrypted["cards"][0]["front"] == "出かける"
        async with client_for(config) as restarted:
            await login(restarted)
            result = (await restarted.get("/api/snapshot")).json()["snapshot"]
            assert result == decrypted
            assert result["cards"][0]["back"] == "to go out"
            assert result["cards"][0]["fields"]["Back"] == "to go out"
            assert result["cards"][0]["interval"] == -60
            assert result["reviews"][2]["ease"] == 0
    asyncio.run(run())


@pytest.mark.parametrize("change", [
    lambda data: data.update(schema_version=True),
    lambda data: data["source"].update(kind="url", url="http://169.254.169.254/"),
    lambda data: data["source"].update(timezone="../../etc/passwd"),
    lambda data: data["cards"].append(copy.deepcopy(data["cards"][0])),
    lambda data: data["cards"][0].update(id=True),
    lambda data: data["cards"][0].update(suspended="false"),
    lambda data: data["cards"][0].update(front="\ud800"),
    lambda data: data["reviews"][0].update(card_id=777),
    lambda data: data["reviews"][0].update(ease=5),
    lambda data: data["reviews"][0].update(time_ms=-1),
    lambda data: data["reviews"].append(copy.deepcopy(data["reviews"][0])),
])
def test_invalid_upload_preserves_previous_data(config, change):
    async def run():
        async with client_for(config) as client:
            headers = {"Authorization": f"Bearer {TOKEN}"}
            assert (await client.post("/api/snapshot", json=snapshot(), headers=headers)).status_code == 200
            before = (config.data_dir / "snapshot.fernet").read_bytes()
            invalid = snapshot()
            change(invalid)
            response = await client.post("/api/snapshot", content=json.dumps(invalid).encode(), headers={**headers, "Content-Type": "application/json"})
            assert response.status_code == 422
            assert "error" in response.json()
            assert (config.data_dir / "snapshot.fernet").read_bytes() == before
    asyncio.run(run())


def test_non_json_excessive_and_ambiguous_uploads_rejected(config):
    async def run():
        small = DashboardConfig(config.password, config.upload_token, config.encryption_key, config.data_dir, max_upload_bytes=2048)
        async with client_for(small) as client:
            headers = {"Authorization": f"Bearer {TOKEN}"}
            assert (await client.post("/api/snapshot", content=b"{}", headers=headers)).status_code == 415
            headers["Content-Type"] = "application/json"
            for body in (b'{"cards":NaN}', b'{"cards":[],"cards":[]}', b'"\xff"'):
                assert (await client.post("/api/snapshot", content=body, headers=headers)).status_code == 400
            assert (await client.post("/api/snapshot", content=b" " * 2049, headers=headers)).status_code == 413
            # The limit is enforced even without a Content-Length header.
            async def chunks():
                yield b" " * 1024
                yield b" " * 1025
            assert (await client.post("/api/snapshot", content=chunks(), headers=headers)).status_code == 413
            assert not config.data_dir.exists()
    asyncio.run(run())


def test_login_rate_limit_and_cookie_tampering(config):
    async def run():
        async with client_for(config) as client:
            await login(client)
            original = client.cookies.get(SESSION_COOKIE)
            client.cookies.clear()
            client.cookies.set(SESSION_COOKIE, original[:-1] + ("x" if original[-1] != "x" else "y"))
            assert (await client.get("/api/snapshot")).status_code == 401
            for _ in range(4):
                assert (await client.post("/api/login", json={"password": "wrong"}, headers={"Origin": ORIGIN})).status_code == 401
            response = await client.post("/api/login", json={"password": PASSWORD}, headers={"Origin": ORIGIN})
            assert response.status_code == 429
            assert response.headers["retry-after"] == "60"
    asyncio.run(run())


def test_invalid_password_unicode_is_a_client_error(config):
    async def run():
        async with client_for(config) as client:
            response = await client.post("/api/login", content=b'{"password":"\\ud800"}', headers={"Origin": ORIGIN, "Content-Type": "application/json"})
            assert response.status_code == 400
            assert (await client.get("/api/session")).json()["authenticated"] is False
    asyncio.run(run())


def test_expired_sessions_and_password_rotation(config, monkeypatch):
    async def run():
        async with client_for(config) as client:
            await login(client)
            cookie = client.cookies.get(SESSION_COOKIE)
        changed = DashboardConfig("a different owner password", config.upload_token, config.encryption_key, config.data_dir)
        async with client_for(changed) as rotated:
            rotated.cookies.set(SESSION_COOKIE, cookie)
            assert (await rotated.get("/api/snapshot")).status_code == 401
        async with client_for(config) as old:
            old.cookies.set(SESSION_COOKIE, cookie)
            assert (await old.get("/api/snapshot")).status_code == 200
            import dashboard
            now = dashboard.time.time()
            monkeypatch.setattr(dashboard.time, "time", lambda: now + 12 * 3600 + 1)
            assert (await old.get("/api/snapshot")).status_code == 401
    asyncio.run(run())


def test_unreadable_encrypted_snapshot_fails_closed(config):
    async def run():
        config.data_dir.mkdir()
        (config.data_dir / "snapshot.fernet").write_bytes(b"not a valid encrypted snapshot")
        async with client_for(config) as client:
            assert (await client.get("/api/snapshot")).status_code == 401
            await login(client)
            response = await client.get("/api/snapshot")
            assert response.status_code == 503
            assert "not a valid encrypted snapshot" not in response.text
    asyncio.run(run())


@pytest.mark.parametrize("name,value", [
    ("password", "short"), ("upload_token", "short"), ("encryption_key", "not-a-key"),
])
def test_missing_or_weak_configuration_refuses_start(config, name, value):
    values = {"password": config.password, "upload_token": config.upload_token, "encryption_key": config.encryption_key, "data_dir": config.data_dir}
    values[name] = value
    with pytest.raises(ValueError):
        create_dashboard(DashboardConfig(**values))


def test_empty_collection_and_markup_are_supported():
    empty = snapshot()
    empty["cards"] = []
    empty["reviews"] = []
    assert validate_snapshot(empty)["cards"] == []
    data = snapshot()
    data["cards"][0]["front"] = '<div>安全 &amp; <i>text</i></div><svg><text>hidden</text></svg><p>次</p>'
    data["cards"][0]["back"] = '<iframe src="http://localhost">hidden</iframe>answer'
    validated = validate_snapshot(data)
    assert validated["cards"][0]["front"] == "安全 & text\n\n次"
    assert validated["cards"][0]["back"] == "answer"


@pytest.mark.parametrize("boundary", [
    '<hr id="answer">', "<hr id='answer'>", "<hr id=answer>",
    '<hr id="answer"/>', "<hr id=answer />", '<HR class="divider" ID="answer">',
])
def test_rendered_answer_removes_front_side_at_anki_boundary(boundary):
    data = snapshot()
    data["cards"][0]["back"] = f'<div>出かける</div>{boundary}<b>to go out</b><script>private</script>'
    assert validate_snapshot(data)["cards"][0]["back"] == "to go out"


@pytest.mark.parametrize("hidden_tag", ["script", "style", "svg", "iframe", "object", "template", "noscript"])
def test_answer_boundary_inside_hidden_markup_is_ignored(hidden_tag):
    data = snapshot()
    hidden = f'<{hidden_tag}>hidden<hr id="answer" />hidden</{hidden_tag}>'
    data["cards"][0]["back"] = f"<b>質問</b>{hidden}<b>答え</b>"
    assert validate_snapshot(data)["cards"][0]["back"] == "質問答え"
    data["cards"][0]["back"] += '<hr id="answer">本当の答え'
    assert validate_snapshot(data)["cards"][0]["back"] == "本当の答え"


def test_custom_answer_keeps_repeated_question_without_anki_boundary():
    data = snapshot()
    data["cards"][0]["front"] = "出かける"
    data["cards"][0]["back"] = '<p>出かける</p><p>出かける means to go out.</p><hr id="other">補足'
    assert validate_snapshot(data)["cards"][0]["back"] == "出かける\n\n出かける means to go out.\n\n補足"


def test_answer_boundary_does_not_remove_front_or_field_content():
    data = snapshot()
    markup = '<b>質問</b><hr id="answer">補足'
    data["cards"][0]["front"] = markup
    data["cards"][0]["fields"]["Front"] = markup
    data["cards"][0]["back"] = markup
    card = validate_snapshot(data)["cards"][0]
    assert card["front"] == "質問\n補足"
    assert card["fields"]["Front"] == "質問\n補足"
    assert card["back"] == "補足"


@pytest.mark.parametrize("public_url", [ORIGIN, "https://Study.Example:443/"])
def test_public_origin_authentication_behind_http_reverse_proxy(config, public_url):
    proxied = DashboardConfig(config.password, config.upload_token, config.encryption_key, config.data_dir, public_url=public_url)

    async def run():
        transport = httpx.ASGITransport(app=create_dashboard(proxied))
        async with httpx.AsyncClient(transport=transport, base_url="http://internal:8000") as client:
            for origin in ("http://internal:8000", "https://attacker.example"):
                response = await client.post("/api/login", json={"password": PASSWORD}, headers={"Origin": origin})
                assert response.status_code == 403
            response = await client.post("/api/login", json={"password": PASSWORD}, headers={"Origin": ORIGIN})
            assert response.status_code == 200
            assert "secure" in response.headers["set-cookie"].lower()
            # The simulated internal HTTP client will not resend Secure cookies;
            # browsers reach the proxy using HTTPS and do resend them.
            cookie = response.cookies.get(SESSION_COOKIE)
            assert (await client.get("/api/snapshot", headers={"Cookie": f"{SESSION_COOKIE}={cookie}"})).status_code == 200
            assert (await client.post("/api/logout", headers={"Origin": "https://attacker.example"})).status_code == 403
            response = await client.post("/api/logout", headers={"Origin": ORIGIN})
            assert response.status_code == 200
            assert "secure" in response.headers["set-cookie"].lower()
    asyncio.run(run())


@pytest.mark.parametrize("public_url", [
    "http://study.example", "https://study.example/path", "https://owner@study.example",
    "https://study.example?query=1", "https://study.example#fragment", "https://",
    "https://study.example:99999", "https://study.example\\attacker.example", "https://study.example\n",
])
def test_invalid_public_origins_are_rejected(config, public_url):
    configured = DashboardConfig(config.password, config.upload_token, config.encryption_key, config.data_dir, public_url=public_url)
    with pytest.raises(ValueError, match="DASHBOARD_PUBLIC_URL"):
        create_dashboard(configured)


def test_public_origin_is_read_from_environment(config, monkeypatch):
    monkeypatch.setenv("DASHBOARD_PASSWORD", config.password)
    monkeypatch.setenv("ANKI_UPLOAD_TOKEN", config.upload_token)
    monkeypatch.setenv("DASHBOARD_ENCRYPTION_KEY", config.encryption_key)
    monkeypatch.setenv("DASHBOARD_PUBLIC_URL", ORIGIN)
    assert DashboardConfig.from_env().public_url == ORIGIN


def test_rich_cards_media_authentication_and_cloud_preservation(config):
    import base64
    import hashlib
    # Real one-pixel PNG fixture, no private card content.
    png = base64.b64decode('iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/x8AAwMCAO+aWQAAAABJRU5ErkJggg==')
    media_id = hashlib.sha256(png).hexdigest()
    data = snapshot()
    data['media'] = {'diagram.png': {'mime': 'image/png', 'data': base64.b64encode(png).decode()}}
    data['cards'][0]['front'] = '<p>C<sub>2</sub>H<sub>4</sub></p><img src="diagram.png" onerror="alert(1)"><img src="https://evil.example/a.png"><script>secret</script>'
    data['cards'][0]['back'] = data['cards'][0]['front'] + '<hr id="answer"><b>Polymer</b>'
    async def run():
        async with client_for(config) as client:
            headers = {'Authorization': f'Bearer {TOKEN}'}
            assert (await client.post('/api/snapshot', json=data, headers=headers)).status_code == 200
            assert (await client.get('/api/media/' + media_id)).status_code == 401
            await login(client)
            result = (await client.get('/api/snapshot')).json()['snapshot']
            assert 'media' not in result
            card = result['cards'][0]
            assert '<sub>2</sub>' in card['front_html']
            assert 'onerror' not in card['front_html'] and 'evil.example' not in card['front_html'] and 'secret' not in card['front_html']
            assert card['back_html'] == '<b>Polymer</b>'
            image = await client.get('/api/media/' + media_id)
            assert image.content == png and image.headers['content-type'] == 'image/png'
            assert image.headers['cache-control'] == 'no-store'
            data.pop('media')
            data['source']['kind'] = 'ankiweb'
            assert (await client.post('/api/snapshot', json=data, headers=headers)).status_code == 200
            assert (await client.get('/api/media/' + media_id)).content == png
            data['cards'][0]['front'] = 'No image now'
            data['cards'][0]['back'] = 'Answer'
            assert (await client.post('/api/snapshot', json=data, headers=headers)).status_code == 200
            assert (await client.get('/api/media/' + media_id)).status_code == 404
    asyncio.run(run())


@pytest.mark.parametrize('attachment', [
    {'mime': 'image/svg+xml', 'data': 'PHN2Zz48L3N2Zz4='},
    {'mime': 'image/png', 'data': 'invalid base64!'},
])
def test_rejects_unsafe_media(attachment):
    data = snapshot()
    data['media'] = {'image.png': attachment}
    with pytest.raises(ValueError):
        validate_snapshot(data)
