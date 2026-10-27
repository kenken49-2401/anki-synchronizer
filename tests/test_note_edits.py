import copy
import json
import subprocess
import time

import pytest

import cloud_tags
import github_tag_queue as queue_module
from cloud_sync import _extract_snapshot
from dashboard import validate_snapshot, SnapshotValidationError
from note_edits import validate_note_changes, NoteEditError
from note_identity import note_fingerprint
from pages_crypto import encrypt
from pages_site import prepare_snapshot, restore_source
from test_cloud_tags import official
from test_github_tag_queue import remote, issue
from test_tag_import import PASSWORD


def edit_package(notes):
    return {'format': 'anki-atlas-note-changes', 'version': 1, 'created_at': '2026-10-27T00:00:00Z',
            'source': {'kind': 'ankiweb', 'profile': 'AnkiWeb'},
            'changes': [{'note_id': int(n.id), 'card_ids': [int(c.id) for c in n.cards()],
                         'model': n.note_type()['name'], 'fields': dict(n.items()),
                         'fingerprint': note_fingerprint(n.note_type()['name'], dict(n.items())),
                         'set_fields': {'Back': '<b>Revised answer</b><br>H<sub>2</sub>O<img src="unchanged.png">'}} for n in notes]}


def test_official_note_edits_preserve_scheduling_history_tags_and_retry(official, monkeypatch):
    seed, notes, auth, endpoint, _ = official
    before_cards = seed.db.all('select id,nid,did,type,queue,due,ivl,factor,reps,lapses from cards order by id')
    before_reviews = seed.db.all('select * from revlog')
    original_collection = cloud_tags.Collection
    calls = []
    def guarded_collection(path):
        col = original_collection(path)
        original = col._backend.full_upload_or_download
        def download(request):
            assert not request.upload
            calls.append(request.upload)
            return original(request)
        col._backend.full_upload_or_download = download
        col.sync_media = lambda *_: pytest.fail('media writes are forbidden')
        return col
    monkeypatch.setattr(cloud_tags, 'Collection', guarded_collection)
    package = edit_package(notes)
    result = cloud_tags.apply_cloud_changes(package, auth.hkey, _test_endpoint=endpoint)
    assert result == {'notes': 2, 'notes_updated': 2, 'verified': True}
    seed.sync_collection(auth, sync_media=False)
    for n in notes:
        actual = seed.get_note(n.id)
        assert actual['Back'] == package['changes'][0]['set_fields']['Back']
        assert actual['Front'] == n['Front']
        assert actual.tags == ['Existing']
    assert seed.db.all('select id,nid,did,type,queue,due,ivl,factor,reps,lapses from cards order by id') == before_cards
    assert seed.db.all('select * from revlog') == before_reviews
    assert cloud_tags.apply_cloud_changes(package, auth.hkey, _test_endpoint=endpoint)['notes_updated'] == 0
    assert calls and not any(calls)


def test_all_note_identities_checked_before_any_writes(official):
    seed, notes, auth, endpoint, _ = official
    package = edit_package(notes)
    other = seed.get_note(notes[1].id)
    other['Front'] = 'Changed on phone first'
    seed.update_note(other)
    seed.sync_collection(auth, sync_media=False)
    with pytest.raises(cloud_tags.TagConflict):
        cloud_tags.apply_cloud_changes(package, auth.hkey, _test_endpoint=endpoint)
    seed.sync_collection(auth, sync_media=False)
    assert seed.get_note(notes[0].id)['Back'] == '<b>answer</b>'
    assert seed.get_note(notes[1].id)['Front'] == 'Changed on phone first'


def test_same_note_conflict_after_upload_is_not_acknowledged(official, monkeypatch):
    seed, notes, auth, endpoint, _ = official
    package = edit_package(notes[:1])
    original = cloud_tags._normal_sync
    count = 0
    def concurrent(col, auth, **kwargs):
        nonlocal count
        count += 1
        result = original(col, auth, **kwargs)
        if count == 2:
            seed.sync_collection(auth, sync_media=False)
            # Advance both Anki's collection timestamp and note modification
            # second, so this is a genuinely later edit rather than a tie.
            time.sleep(1.1)
            n = seed.get_note(notes[0].id)
            n['Back'] = 'Newer phone edit after upload'
            seed.update_note(n)
            seed.sync_collection(auth, sync_media=False)
            with cloud_tags._download(auth, test_local_only=True) as remote:
                assert remote.get_note(notes[0].id)['Back'] == 'Newer phone edit after upload'
        return result
    monkeypatch.setattr(cloud_tags, '_normal_sync', concurrent)
    with pytest.raises(cloud_tags.TagConflict):
        cloud_tags.apply_cloud_changes(package, auth.hkey, _test_endpoint=endpoint)


def test_raw_editable_fields_survive_sanitization_and_seed_rebuild(official):
    seed, notes, *_ = official
    n = seed.get_note(notes[0].id)
    n['Back'] = '<div onclick="private()">H<sub>2</sub>O {{c1::water}}<img src="preserve.png"></div>'
    seed.update_note(n)
    raw = _extract_snapshot(seed, timezone='Asia/Tokyo', query='', allow_empty=False)
    safe = prepare_snapshot(raw)
    rebuilt = prepare_snapshot(restore_source(safe))
    for data in (safe, rebuilt):
        c = next(c for c in data['cards'] if c['note_id'] == n.id)
        assert c['editable_fields'] == dict(n.items())
        assert c['fields']['Back'] != n['Back']
        assert c['tag_identity'] == note_fingerprint(c['model'], c['editable_fields'])
    broken = copy.deepcopy(raw)
    broken['cards'][0]['editable_fields']['Back'] = 'incorrect original'
    with pytest.raises(SnapshotValidationError):
        validate_snapshot(broken)


@pytest.mark.parametrize('mutation', ['fingerprint', 'unknown_field', 'unchanged', 'wrong_card', 'duplicate', 'extra', 'surrogate'])
def test_invalid_edits_rejected_before_network(official, monkeypatch, mutation):
    seed, notes, auth, endpoint, _ = official
    package = edit_package(notes[:1]); c = package['changes'][0]
    if mutation == 'fingerprint': c['fingerprint'] = '0' * 64
    elif mutation == 'unknown_field': c['set_fields'] = {'Unknown': 'bad'}
    elif mutation == 'unchanged': c['set_fields'] = {'Back': c['fields']['Back']}
    elif mutation == 'wrong_card': c['card_ids'] = [0]
    elif mutation == 'duplicate': package['changes'].append(copy.deepcopy(c))
    elif mutation == 'extra': c['delete_cards'] = True
    elif mutation == 'surrogate': c['set_fields']['Back'] = '\ud800'
    monkeypatch.setattr(cloud_tags, '_download', lambda *_args, **_kwargs: pytest.fail('must not contact Anki'))
    with pytest.raises(NoteEditError):
        cloud_tags.apply_cloud_changes(package, auth.hkey, _test_endpoint=endpoint)


def test_owner_note_request_uses_encrypted_body_and_verified_ack(remote, official, monkeypatch):
    rows, requests = remote
    _, notes, *_ = official
    package = edit_package(notes[:1])
    body = queue_module.NOTE_MARKER + '\n```json\n' + json.dumps(encrypt(package, PASSWORD), separators=(',', ':')) + '\n```'
    rows[1] = {**issue(), 'title': queue_module.NOTE_TITLE, 'body': body}
    received = []
    monkeypatch.setattr(queue_module, 'apply_cloud_changes', lambda p, *_: (received.append(p) or {'verified': True}))
    with queue_module.GitHubQueue('owner/repo', 'job-test-token') as queue:
        assert queue_module.process_queue(queue, PASSWORD, 'test-key')['applied'] == 1
    assert received == [package] and rows[1]['state'] == 'closed'
    assert all('Revised answer' not in r.content.decode() for r in requests)


def test_note_marker_cannot_be_used_for_a_tag_payload():
    from test_tag_import import package
    body = queue_module.NOTE_MARKER + '\n```json\n' + json.dumps(encrypt(package(), PASSWORD)) + '\n```'
    with pytest.raises(queue_module.QueueError):
        queue_module.parse_body(body, PASSWORD)


@pytest.mark.parametrize('wrong_title', [False, True])
def test_note_conflicts_and_mismatched_titles_stay_open_for_attention(remote, monkeypatch, wrong_title):
    fields = {'Front': 'Synthetic question', 'Back': 'Synthetic answer'}
    package = {'format': 'anki-atlas-note-changes', 'version': 1, 'created_at': '2026-10-27T00:00:00Z',
               'source': {'kind': 'ankiweb', 'profile': 'AnkiWeb'},
               'changes': [{'note_id': 99, 'card_ids': [100], 'model': 'Basic', 'fields': fields,
                            'fingerprint': note_fingerprint('Basic', fields), 'set_fields': {'Back': 'Revised'}}]}
    body = queue_module.NOTE_MARKER + '\n```json\n' + json.dumps(encrypt(package, PASSWORD)) + '\n```'
    rows, _ = remote
    rows[1] = {**issue(), 'title': queue_module.TITLE if wrong_title else queue_module.NOTE_TITLE, 'body': body}
    def reject(*_):
        if wrong_title:
            pytest.fail('A request with a mismatched title must not contact Anki')
        raise cloud_tags.TagConflict('synthetic conflict')
    monkeypatch.setattr(queue_module, 'apply_cloud_changes', reject)
    with queue_module.GitHubQueue('owner/repo', 'job-test-token') as queue:
        assert queue_module.process_queue(queue, PASSWORD, 'test-key')['rejected'] == 1
    assert rows[1]['state'] == 'open'
    assert rows[1]['title'] == (queue_module.ATTENTION_TITLE if wrong_title else queue_module.NOTE_ATTENTION_TITLE)


def test_browser_fingerprint_matches_python_with_unicode_names():
    fields = {'\U0001f600': 'emoji', '\ue000': '<b>private</b>', '裏': '{{c1::答え}}'}
    script = "import{noteFingerprint}from'./web/note-edits.mjs';let s='';for await(const c of process.stdin)s+=c;console.log(await noteFingerprint('Basic',JSON.parse(s)))"
    result = subprocess.run(['node','--input-type=module','-e',script], input=json.dumps(fields), text=True, capture_output=True, check=True)
    assert result.stdout.strip() == note_fingerprint('Basic', fields)
