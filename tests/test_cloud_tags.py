import os
import socket
import subprocess
import sys
import time
from unittest.mock import patch

from anki.collection import Collection
from anki import sync_pb2
import pytest

import cloud_tags
from note_identity import note_fingerprint
from test_tag_import import package


@pytest.fixture
def official(tmp_path, monkeypatch):
    with socket.socket() as sock:
        sock.bind(('127.0.0.1', 0))
        port = sock.getsockname()[1]
    endpoint = f'http://127.0.0.1:{port}/'
    monkeypatch.setenv('NO_PROXY', os.environ.get('NO_PROXY', '') + ',localhost,127.0.0.1')
    env = os.environ.copy()
    env.update(SYNC_HOST='127.0.0.1', SYNC_PORT=str(port), SYNC_BASE=str(tmp_path / 'remote'), SYNC_USER1='user:password')
    server = subprocess.Popen([sys.executable, '-m', 'anki.syncserver'], env=env,
                              stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    seed = None
    try:
        for _ in range(100):
            try:
                with socket.create_connection(('127.0.0.1', port), timeout=.1):
                    break
            except OSError:
                time.sleep(.03)
        seed = Collection(str(tmp_path / 'phone.anki2'))
        notes = []
        for front in ('C<sub>2</sub>H<sub>4</sub>', 'another note'):
            note = seed.new_note(seed.models.by_name('Basic'))
            note['Front'], note['Back'] = front, '<b>answer</b>'
            note.tags = ['Existing']
            seed.add_note(note, seed.decks.id('Study'))
            notes.append(note)
        card = notes[0].cards()[0]
        card.start_timer()
        answer = seed.sched.build_answer(card=card, states=seed._backend.get_scheduling_states(card.id), rating=3)
        answer.milliseconds_taken = 12345
        seed.sched.answer_card(answer)
        auth = seed.sync_login('user', 'password', endpoint)
        seed.sync_collection(auth, sync_media=False)
        seed.close_for_full_sync()
        # Fixture creation only; production cloud tag worker forbids this direction.
        seed._backend.full_upload_or_download(sync_pb2.FullUploadOrDownloadRequest(auth=auth, upload=True))
        seed.reopen(after_full_sync=True)
        changes = [{'note_id': int(n.id), 'card_ids': [int(c.id) for c in n.cards()],
                    'model': n.note_type()['name'], 'fingerprint': note_fingerprint(n.note_type()['name'], dict(n.items())),
                    'add_tags': ['要復習', 'Chemistry::New']} for n in notes]
        yield seed, notes, auth, endpoint, changes
    finally:
        if seed is not None:
            seed.close()
        server.terminate()
        server.wait(timeout=5)


def test_official_incremental_tags_preserve_notes_cards_reviews_and_retry(official, monkeypatch):
    seed, notes, auth, endpoint, changes = official
    before_cards = seed.db.all('select id,nid,did,type,queue,due,ivl,factor,reps,lapses from cards order by id')
    before_reviews = seed.db.all('select * from revlog')
    download = cloud_tags.Collection
    calls = []
    def collection(path):
        col = download(path)
        backend = col._backend.full_upload_or_download
        def guarded(request):
            calls.append(request.upload)
            assert not request.upload, 'Full uploads are forbidden'
            return backend(request)
        col._backend.full_upload_or_download = guarded
        col.sync_media = lambda *_: pytest.fail('media sync forbidden')
        return col
    monkeypatch.setattr(cloud_tags, 'Collection', collection)
    first = cloud_tags.apply_cloud_changes(package(changes), auth.hkey, _test_endpoint=endpoint)
    assert first == {'notes': 2, 'tags_added': 4, 'verified': True}
    seed.sync_collection(auth, sync_media=False)
    for note in notes:
        actual = seed.get_note(note.id)
        assert set(actual.tags) == {'Existing', '要復習', 'Chemistry::New'}
        assert dict(actual.items()) == dict(note.items())
    assert seed.db.all('select id,nid,did,type,queue,due,ivl,factor,reps,lapses from cards order by id') == before_cards
    assert seed.db.all('select * from revlog') == before_reviews
    second = cloud_tags.apply_cloud_changes(package(changes), auth.hkey, _test_endpoint=endpoint)
    assert second['tags_added'] == 0 and second['verified']
    assert calls and not any(calls)


def test_all_identities_preflight_before_any_upload(official):
    seed, notes, auth, endpoint, changes = official
    changed = seed.get_note(notes[1].id)
    changed['Front'] = 'changed on phone'
    seed.update_note(changed)
    seed.sync_collection(auth, sync_media=False)
    with pytest.raises(cloud_tags.TagConflict):
        cloud_tags.apply_cloud_changes(package(changes), auth.hkey, _test_endpoint=endpoint)
    seed.sync_collection(auth, sync_media=False)
    assert seed.get_note(notes[0].id).tags == ['Existing']
    assert seed.get_note(notes[1].id)['Front'] == 'changed on phone'


def test_another_phone_note_update_merges_during_tag_sync(official, monkeypatch):
    seed, notes, auth, endpoint, changes = official
    original = cloud_tags._normal_sync
    count = 0
    def sync(col, auth, **kwargs):
        nonlocal count
        count += 1
        if count == 2:
            note = seed.get_note(notes[1].id)
            note['Back'] = 'phone edit on a different note'
            seed.update_note(note)
            seed.sync_collection(auth, sync_media=False)
        return original(col, auth, **kwargs)
    monkeypatch.setattr(cloud_tags, '_normal_sync', sync)
    cloud_tags.apply_cloud_changes(package(changes[:1]), auth.hkey, _test_endpoint=endpoint)
    seed.sync_collection(auth, sync_media=False)
    assert '要復習' in seed.get_note(notes[0].id).tags
    assert seed.get_note(notes[1].id)['Back'] == 'phone edit on a different note'


def test_full_sync_requirement_never_selects_full_upload():
    class Fake:
        def sync_collection(self, auth, sync_media):
            assert not sync_media
            return sync_pb2.SyncCollectionResponse(required=sync_pb2.SyncCollectionResponse.FULL_UPLOAD)
    with pytest.raises(cloud_tags.CloudTagError, match='Full collection sync'):
        cloud_tags._normal_sync(Fake(), sync_pb2.SyncAuth())


@pytest.mark.parametrize('endpoint', ['http://sync.ankiweb.net/', 'https://evil.example/', 'https://sync.ankiweb.net/?key=x'])
def test_cloud_tag_destinations_restricted(endpoint):
    with pytest.raises(ValueError):
        cloud_tags.apply_cloud_changes(package(), 'test-key', endpoint)
