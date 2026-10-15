import copy
import json
import os

import httpx
import pytest

import connector
from connector import ConnectorError, export_snapshot, main, save_snapshot, upload_snapshot


def card(card_id=101, note_id=201):
    return {
        "cardId": card_id, "note": note_id, "deckName": "日本語::基礎",
        "modelName": "Basic", "question": "<b>問題</b>", "answer": "<hr>答え",
        "reps": 3, "lapses": 1, "interval": -30, "due": 400, "queue": -1,
    }


def note(note_id=201):
    return {
        "noteId": note_id, "tags": ["science::physics", "exam", "exam"],
        "fields": {"Front": {"value": "問題", "order": 0}, "Back": {"value": "答え", "order": 1}},
    }


@pytest.fixture
def anki_mock(monkeypatch):
    responses = {
        "getActiveProfile": "自分のプロファイル",
        "getProfiles": ["自分のプロファイル"],
        "findCards": [101],
        "cardsInfo": [card()],
        "notesInfo": [note()],
        "getReviewsOfCards": {"101": [
            {"id": 1740000000000, "ease": 1, "time": 4500, "type": 0},
            {"id": 1740000010000, "ease": 3, "time": 2500, "type": 1},
            {"id": 1740000020000, "ease": 0, "time": 0, "type": 4},
        ]},
    }
    calls = []
    options = []

    def handler(request):
        payload = json.loads(request.content)
        calls.append(payload)
        action = payload["action"]
        result = responses[action]
        if callable(result):
            result = result(payload)
        if isinstance(result, Exception):
            return httpx.Response(200, json={"result": None, "error": str(result)})
        return httpx.Response(200, json={"result": copy.deepcopy(result), "error": None})

    client_type = httpx.Client

    def client(**kwargs):
        options.append(kwargs)
        return client_type(transport=httpx.MockTransport(handler), **kwargs)

    monkeypatch.setattr(connector.httpx, "Client", client)
    return responses, calls, options


def test_exports_note_tags_rendered_cards_and_full_review_history(anki_mock):
    _, calls, options = anki_mock
    snapshot = export_snapshot(api_key="local-secret", expected_profile="自分のプロファイル", query="tag:exam")
    assert snapshot["schema_version"] == 1
    assert snapshot["source"] == {"profile": "自分のプロファイル", "kind": "ankiconnect", "timezone": "Asia/Tokyo"}
    assert snapshot["synced_at"].endswith("+00:00")
    assert snapshot["cards"] == [{
        "id": 101, "note_id": 201, "deck": "日本語::基礎", "model": "Basic",
        "tags": ["exam", "science::physics"], "front": "<b>問題</b>", "back": "<hr>答え",
        "fields": {"Front": "問題", "Back": "答え"}, "reps": 3, "lapses": 1,
        "interval": -30, "due": 400, "suspended": True,
    }]
    assert [review["ease"] for review in snapshot["reviews"]] == [1, 3, 0]
    assert [review["time_ms"] for review in snapshot["reviews"]] == [4500, 2500, 0]
    assert all(review["card_id"] == 101 for review in snapshot["reviews"])
    assert all(call["version"] == 6 and call["key"] == "local-secret" for call in calls)
    assert next(call for call in calls if call["action"] == "findCards")["params"] == {"query": "tag:exam"}
    assert {call["action"] for call in calls} <= {"getActiveProfile", "findCards", "cardsInfo", "notesInfo", "getReviewsOfCards"}
    assert options[0]["trust_env"] is False
    assert options[0]["follow_redirects"] is False


def test_cards_are_batched_and_shared_notes_are_not_duplicated(monkeypatch, anki_mock):
    responses, calls, _ = anki_mock
    monkeypatch.setattr(connector, "BATCH_SIZE", 2)
    responses["findCards"] = [101, 102, 103]
    responses["cardsInfo"] = lambda payload: [card(cid) for cid in payload["params"]["cards"]]
    responses["getReviewsOfCards"] = lambda payload: {str(cid): [] for cid in payload["params"]["cards"]}
    snapshot = export_snapshot()
    assert len(snapshot["cards"]) == 3
    assert [call["params"]["cards"] for call in calls if call["action"] == "cardsInfo"] == [[101, 102], [103]]
    assert all(call["params"]["notes"] == [201] for call in calls if call["action"] == "notesInfo")


def test_older_addon_single_profile_fallback_is_read_only(anki_mock):
    responses, calls, _ = anki_mock
    responses["getActiveProfile"] = RuntimeError("unsupported action")
    assert export_snapshot()["source"]["profile"] == "自分のプロファイル"
    assert "getProfiles" in [call["action"] for call in calls]
    assert not {"loadProfile", "sync", "requestPermission"} & {call["action"] for call in calls}


def test_older_addon_multiple_profiles_refuses_ambiguous_account(anki_mock):
    responses, calls, _ = anki_mock
    responses["getActiveProfile"] = RuntimeError("unsupported action")
    responses["getProfiles"] = ["personal", "work"]
    with pytest.raises(ConnectorError, match="複数プロファイル"):
        export_snapshot(expected_profile="personal")
    assert "findCards" not in [call["action"] for call in calls]


def test_wrong_profile_stops_before_reading_cards(anki_mock):
    _, calls, _ = anki_mock
    with pytest.raises(ConnectorError, match="異なります"):
        export_snapshot(expected_profile="someone else")
    assert [call["action"] for call in calls] == ["getActiveProfile"]


def test_profile_changed_during_export_refuses_snapshot(anki_mock):
    responses, _, _ = anki_mock
    names = iter(["personal", "work"])
    responses["getActiveProfile"] = lambda _: next(names)
    with pytest.raises(ConnectorError, match="取得中"):
        export_snapshot()


@pytest.mark.parametrize("endpoint", [
    "https://example.com", "http://192.168.1.2:8765", "http://127.0.0.1:8765/path",
    "http://user:secret@localhost:8765", "http://@localhost:8765", "http://localhost:99999",
    "file:///tmp/anki", "http://localhost:8765?secret=value",
])
def test_anki_endpoint_rejects_non_loopback_and_credentials(endpoint, anki_mock):
    _, calls, _ = anki_mock
    with pytest.raises(ConnectorError, match="ローカル URL"):
        export_snapshot(endpoint)
    assert calls == []


def test_loopback_ipv6_endpoint_is_supported(anki_mock):
    assert export_snapshot("http://[::1]:8765")["cards"]


def test_api_errors_do_not_expose_remote_data_or_secrets(anki_mock):
    responses, _, _ = anki_mock
    responses["findCards"] = RuntimeError("private-field api-key local-secret")
    with pytest.raises(ConnectorError) as error:
        export_snapshot(api_key="local-secret")
    assert "findCards" in str(error.value)
    assert "local-secret" not in str(error.value)
    assert "private-field" not in str(error.value)


@pytest.mark.parametrize("name,value", [
    ("findCards", [101, 101]),
    ("cardsInfo", [{}]),
    ("notesInfo", []),
    ("getReviewsOfCards", {}),
    ("getReviewsOfCards", {"101": [{"id": 42, "ease": 5, "time": 1, "type": 0}]}),
    ("getReviewsOfCards", {"101": [{"id": 42, "ease": True, "time": 1, "type": 0}]}),
    ("getReviewsOfCards", {"101": [{"id": 42, "ease": 3, "time": -1, "type": 0}]}),
])
def test_malformed_and_inconsistent_results_are_rejected(name, value, anki_mock):
    responses, _, _ = anki_mock
    responses[name] = value
    with pytest.raises(ConnectorError):
        export_snapshot()


def test_duplicate_review_ids_are_rejected(anki_mock):
    responses, _, _ = anki_mock
    responses["getReviewsOfCards"]["101"].append(responses["getReviewsOfCards"]["101"][0])
    with pytest.raises(ConnectorError, match="重複"):
        export_snapshot()


def test_empty_collection_is_a_valid_snapshot(anki_mock):
    responses, calls, _ = anki_mock
    responses["findCards"] = []
    snapshot = export_snapshot()
    assert snapshot["cards"] == snapshot["reviews"] == []
    assert [call["action"] for call in calls] == ["getActiveProfile", "findCards", "getActiveProfile"]


def test_limits_error_without_truncating(monkeypatch, anki_mock):
    monkeypatch.setattr(connector, "MAX_CARDS", 0)
    with pytest.raises(ConnectorError, match="--query"):
        export_snapshot()
    monkeypatch.setattr(connector, "MAX_CARDS", 10)
    monkeypatch.setattr(connector, "MAX_REVIEWS", 1)
    with pytest.raises(ConnectorError, match="--query"):
        export_snapshot()


def test_response_size_limit_is_enforced(monkeypatch, anki_mock):
    monkeypatch.setattr(connector, "MAX_RESPONSE_BYTES", 2)
    with pytest.raises(ConnectorError, match="上限"):
        export_snapshot()


def test_invalid_timezone_fails_before_access(anki_mock):
    _, calls, _ = anki_mock
    with pytest.raises(ConnectorError, match="タイムゾーン"):
        export_snapshot(timezone="Invalid/Timezone")
    assert not calls


def test_upload_uses_bearer_and_expected_path_without_redirects(monkeypatch):
    calls = []
    options = []
    client_type = httpx.Client

    def handler(request):
        calls.append(request)
        return httpx.Response(200, json={"ok": True})

    def client(**kwargs):
        options.append(kwargs)
        return client_type(transport=httpx.MockTransport(handler), **kwargs)

    monkeypatch.setattr(connector.httpx, "Client", client)
    upload_snapshot("https://dashboard.example/base", "private-token", {"schema_version": 1})
    assert str(calls[0].url) == "https://dashboard.example/base/api/snapshot"
    assert calls[0].headers["authorization"] == "Bearer private-token"
    assert json.loads(calls[0].content) == {"schema_version": 1}
    assert options[0]["follow_redirects"] is False
    assert options[0]["trust_env"] is True
    upload_snapshot("http://127.0.0.1:8000/api/snapshot", "private-token", {})
    assert str(calls[1].url) == "http://127.0.0.1:8000/api/snapshot"
    assert options[1]["trust_env"] is False


def test_upload_rejects_plaintext_remote_host():
    with pytest.raises(ConnectorError, match="HTTPS"):
        upload_snapshot("http://dashboard.example", "private-token", {})


@pytest.mark.parametrize("token", ["", "token\r\nX-Header: injected", "token with space", "秘密トークン"])
def test_upload_rejects_invalid_bearer_without_exposing_value(token):
    with pytest.raises(ConnectorError, match="トークン") as error:
        upload_snapshot("https://dashboard.example", token, {})
    if token:
        assert token not in str(error.value)


def test_network_error_and_redirect_do_not_expose_credentials(monkeypatch):
    client_type = httpx.Client

    def handler(request):
        raise httpx.ConnectError("private-token", request=request)

    monkeypatch.setattr(connector.httpx, "Client", lambda **kwargs: client_type(transport=httpx.MockTransport(handler), **kwargs))
    with pytest.raises(ConnectorError) as error:
        upload_snapshot("https://dashboard.example", "private-token", {})
    assert "private-token" not in str(error.value)

    def redirect(request):
        return httpx.Response(307, headers={"Location": "https://another.example"})

    monkeypatch.setattr(connector.httpx, "Client", lambda **kwargs: client_type(transport=httpx.MockTransport(redirect), **kwargs))
    with pytest.raises(ConnectorError, match="307"):
        upload_snapshot("https://dashboard.example", "private-token", {})


def test_json_output_is_atomic_and_private(tmp_path):
    path = tmp_path / "snapshot.json"
    path.write_text("old")
    snapshot = {"cards": [{"front": "個人カード"}]}
    save_snapshot(path, snapshot)
    assert json.loads(path.read_text()) == snapshot
    if os.name != "nt":
        assert path.stat().st_mode & 0o777 == 0o600
    assert list(tmp_path.iterdir()) == [path]


def test_cli_missing_token_stops_before_export(monkeypatch, capsys):
    monkeypatch.delenv("ANKI_UPLOAD_TOKEN", raising=False)
    monkeypatch.setattr(connector, "export_snapshot", lambda **_: pytest.fail("should not read cards"))
    assert main(["--server", "https://dashboard.example"]) == 1
    assert "ANKI_UPLOAD_TOKEN" in capsys.readouterr().err


def test_cli_uses_environment_secrets_and_never_prints_card_data(monkeypatch, tmp_path, capsys):
    calls = []
    snapshot = {"cards": [{"front": "private-card"}], "reviews": []}
    monkeypatch.setenv("ANKI_CONNECT_API_KEY", "private-key")
    monkeypatch.setenv("ANKI_UPLOAD_TOKEN", "private-token")

    def export(**kwargs):
        calls.append(kwargs)
        return snapshot

    uploads = []
    monkeypatch.setattr(connector, "export_snapshot", export)
    monkeypatch.setattr(connector, "upload_snapshot", lambda *args: uploads.append(args))
    path = tmp_path / "snapshot.json"
    assert main(["--server", "https://dashboard.example", "--profile", "personal", "--output", str(path)]) == 0
    assert calls[0]["api_key"] == "private-key"
    assert calls[0]["expected_profile"] == "personal"
    assert uploads[0] == ("https://dashboard.example", "private-token", snapshot)
    output = capsys.readouterr()
    assert "カード 1 件" in output.out
    assert not any(secret in output.out + output.err for secret in ["private-card", "private-key", "private-token"])


def test_watch_retries_after_sleep_when_desktop_unavailable(monkeypatch, capsys):
    attempts = []

    def export(**kwargs):
        attempts.append(kwargs)
        if len(attempts) == 1:
            raise ConnectorError("Anki を起動してください。")
        return {"cards": [], "reviews": []}

    sleeps = []

    def sleep(seconds):
        sleeps.append(seconds)
        if len(sleeps) == 2:
            raise KeyboardInterrupt

    monkeypatch.setenv("ANKI_UPLOAD_TOKEN", "private-token")
    monkeypatch.setattr(connector, "export_snapshot", export)
    monkeypatch.setattr(connector, "upload_snapshot", lambda *args: None)
    monkeypatch.setattr(connector.time, "sleep", sleep)
    assert main(["--server", "https://dashboard.example", "--watch", "30"]) == 0
    assert len(attempts) == 2
    assert sleeps == [30, 30]
    assert "同期待機" in capsys.readouterr().err
