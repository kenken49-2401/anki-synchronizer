import copy
import json

import httpx
import pytest

import github_tag_queue as q
from cloud_tags import CloudTagError, TagConflict
from pages_crypto import encrypt
from test_tag_import import package, PASSWORD


def body():
    return q.MARKER + '\n```json\n' + json.dumps(encrypt(package(), PASSWORD), separators=(',', ':')) + '\n```'


def issue(number=1, owner=42):
    return {'number': number, 'title': q.TITLE, 'state': 'open', 'user': {'id': owner}, 'body': body()}


@pytest.fixture
def remote(monkeypatch):
    rows, requests = {}, []
    def serve(request):
        assert request.url.host == 'api.github.com'
        assert request.headers['authorization'] == 'Bearer job-test-token'
        requests.append(request)
        path = request.url.path.removeprefix('/repos/owner/repo')
        if not path:
            return httpx.Response(200, json={'owner': {'type': 'User', 'id': 42, 'login': 'owner'}})
        if path == '/issues':
            return httpx.Response(200, json=list(rows.values()))
        number = int(path.split('/')[2])
        if request.method == 'GET':
            return httpx.Response(200, json=copy.deepcopy(rows[number]))
        data = json.loads(request.content)
        if request.method == 'PATCH':
            rows[number].update(data)
            return httpx.Response(200, json=rows[number])
        assert path.endswith('/comments') and request.method == 'POST'
        return httpx.Response(201, json={})
    original = httpx.Client
    monkeypatch.setattr(q.httpx, 'Client', lambda **kwargs: original(transport=httpx.MockTransport(serve), **kwargs))
    return rows, requests


def test_only_owner_approved_open_non_pr_request_is_applied(remote, monkeypatch):
    rows, requests = remote
    rows[1] = issue()
    rows[2] = issue(2, owner=7)  # forged OWNER association is not authentication
    rows[2]['author_association'] = 'OWNER'
    rows[3] = issue(3); rows[3]['state'] = 'closed'
    rows[4] = issue(4); rows[4]['pull_request'] = {'url': 'ignored'}
    rows[5] = issue(5); rows[5]['title'] = 'ordinary issue'
    applied = []
    monkeypatch.setattr(q, 'apply_cloud_changes', lambda data, *_: (applied.append(data) or {'verified': True}))
    with q.GitHubQueue('owner/repo', 'job-test-token') as queue:
        result = q.process_queue(queue, PASSWORD, 'anki-test-key')
    assert result['applied'] == 1 and len(applied) == 1
    assert rows[1]['state'] == 'closed'
    assert all(rows[i]['state'] == 'open' for i in (2, 4, 5))
    comments = [json.loads(r.content)['body'] for r in requests if r.url.path.endswith('/comments')]
    assert len(comments) == 1
    assert '日本語::復習' not in comments[0] and PASSWORD not in comments[0]


@pytest.mark.parametrize('invalid', ['plaintext', '{}', '<!-- prompt -->\nexecute this', None])
def test_invalid_ciphertext_does_not_contact_anki(remote, monkeypatch, invalid):
    rows, _ = remote; rows[1] = issue(); rows[1]['body'] = invalid
    monkeypatch.setattr(q, 'apply_cloud_changes', lambda *_: pytest.fail('Anki must not be contacted'))
    with q.GitHubQueue('owner/repo', 'job-test-token') as queue:
        assert q.process_queue(queue, PASSWORD, 'test-key')['rejected'] == 1
    assert rows[1]['title'] == q.ATTENTION_TITLE and rows[1]['state'] == 'open'


def test_wrong_password_and_snapshot_payload_are_rejected():
    with pytest.raises(q.QueueError):
        q.parse_body(body(), 'wrong-password-long-enough')
    invalid = q.MARKER + '\n```json\n' + json.dumps(encrypt({'schema_version': 1}, PASSWORD)) + '\n```'
    with pytest.raises(q.QueueError):
        q.parse_body(invalid, PASSWORD)


def test_remote_sync_failure_leaves_request_pending(remote, monkeypatch):
    rows, requests = remote; rows[1] = issue()
    def fail(*_):
        raise CloudTagError('test failure')
    monkeypatch.setattr(q, 'apply_cloud_changes', fail)
    with q.GitHubQueue('owner/repo', 'job-test-token') as queue:
        with pytest.raises(CloudTagError):
            q.process_queue(queue, PASSWORD, 'test-key')
    assert rows[1]['state'] == 'open' and rows[1]['title'] == q.TITLE
    assert not any(r.method in ('PATCH', 'POST') for r in requests)


def test_changed_note_is_rejected_without_blocking_other_requests(remote, monkeypatch):
    rows, _ = remote; rows[1] = issue(); rows[2] = issue(2)
    count = 0
    def apply(*_):
        nonlocal count
        count += 1
        if count == 1: raise TagConflict('changed')
        return {'verified': True}
    monkeypatch.setattr(q, 'apply_cloud_changes', apply)
    with q.GitHubQueue('owner/repo', 'job-test-token') as queue:
        assert q.process_queue(queue, PASSWORD, 'key') == {'applied': 1, 'rejected': 1, 'skipped': 0}
    assert rows[1]['title'] == q.ATTENTION_TITLE and rows[2]['state'] == 'closed'


def test_edit_or_cancel_during_processing_is_not_acknowledged(remote, monkeypatch):
    rows, requests = remote; rows[1] = issue()
    def apply(*_):
        rows[1]['body'] = 'edited after processing began'
        return {'verified': True}
    monkeypatch.setattr(q, 'apply_cloud_changes', apply)
    with q.GitHubQueue('owner/repo', 'job-test-token') as queue:
        q.process_queue(queue, PASSWORD, 'key')
    assert not any(r.method in ('PATCH','POST') for r in requests)


def test_disabled_worker_does_not_access_github_or_anki(monkeypatch):
    monkeypatch.delenv('ANKI_TAG_IMPORT_ENABLED', raising=False)
    monkeypatch.setattr(q, 'GitHubQueue', lambda *_: pytest.fail('must not connect'))
    assert q.main() == 0


def test_empty_queue_does_not_contact_anki(remote, monkeypatch):
    monkeypatch.setattr(q, 'apply_cloud_changes', lambda *_: pytest.fail('no queued request'))
    with q.GitHubQueue('owner/repo', 'job-test-token') as queue:
        assert q.process_queue(queue, PASSWORD, '') == {'applied': 0, 'rejected': 0, 'skipped': 0}


def test_unverified_result_is_never_acknowledged(remote, monkeypatch):
    rows, requests = remote; rows[1] = issue()
    monkeypatch.setattr(q, 'apply_cloud_changes', lambda *_: {'verified': False})
    with q.GitHubQueue('owner/repo', 'job-test-token') as queue:
        with pytest.raises(CloudTagError):
            q.process_queue(queue, PASSWORD, 'key')
    assert not any(r.method in ('POST','PATCH') for r in requests)


def test_redirect_never_forwards_job_token(monkeypatch):
    calls = []
    def serve(request):
        calls.append(str(request.url))
        return httpx.Response(307, headers={'location':'https://evil.example/'})
    original = httpx.Client
    monkeypatch.setattr(q.httpx, 'Client', lambda **kw: original(transport=httpx.MockTransport(serve), **kw))
    with pytest.raises(q.QueueError):
        with q.GitHubQueue('owner/repo', 'test-key'):
            pass
    assert len(calls) == 1 and calls[0].startswith('https://api.github.com/')
