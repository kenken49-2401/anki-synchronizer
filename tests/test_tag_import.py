import copy
import json

import pytest

import tag_import as ti
from connector import AnkiConnect, ConnectorError
from note_identity import note_fingerprint
from pages_crypto import encrypt

PASSWORD = 'long-test-password-for-tag-patches'


def change(nid=1, cid=11):
    return {'note_id': nid, 'card_ids': [cid], 'model': 'Basic',
            'fingerprint': note_fingerprint('Basic', {'Front': '<b>日本語</b>', 'Back': 'answer'}),
            'add_tags': ['日本語::復習', 'new']}


def package(changes=None):
    return {'format': 'anki-atlas-tag-changes', 'version': 1,
            'created_at': '2026-10-16T00:00:00Z',
            'source': {'kind': 'ankiconnect', 'profile': 'Main'},
            'changes': changes if changes is not None else [change()]}


class FakeAnki:
    def __init__(self):
        self.profile = 'Main'
        self.calls = []
        self.notes = {i: {'noteId': i, 'modelName': 'Basic',
                         'fields': {'Front': {'value': '<b>日本語</b>'}, 'Back': {'value': 'answer'}},
                         'tags': ['existing']} for i in (1, 2)}
        self.cards = {11: {'cardId': 11, 'note': 1}, 12: {'cardId': 12, 'note': 2}}
        self.fail_note = None
        self.ignore_add = False
        self.switch_after_preflight = False

    def __enter__(self):
        return self

    def __exit__(self, *args):
        pass

    def active_profile(self):
        self.calls.append(('profile', {}))
        return self.profile

    def call(self, action, **params):
        self.calls.append((action, params))
        if action == 'notesInfo':
            return copy.deepcopy([self.notes[n] for n in params['notes']])
        if action == 'cardsInfo':
            if self.switch_after_preflight:
                self.profile = 'Other'
            return copy.deepcopy([self.cards[n] for n in params['cards']])
        if action == 'addTags':
            nid = params['notes'][0]
            if nid == self.fail_note:
                raise ConnectorError('secret remote data')
            if not self.ignore_add:
                self.notes[nid]['tags'] = list(set(self.notes[nid]['tags']) | set(params['tags'].split()))
            return None
        if action == 'sync':
            return None
        raise AssertionError(action)


@pytest.fixture
def client(monkeypatch):
    fake = FakeAnki()
    monkeypatch.setattr(ti, 'AnkiConnect', lambda *args: fake)
    return fake


@pytest.fixture
def write(tmp_path):
    def write_package(value=None):
        path = tmp_path / 'changes.json'
        path.write_text(json.dumps(encrypt(value or package(), PASSWORD)), encoding='utf-8')
        return path
    return write_package


def mutations(client):
    return [a for a, _ in client.calls if a in ('addTags', 'sync')]


def test_dry_run_reads_all_identities_without_mutating(client, write):
    result = ti.import_tag_changes(write(), PASSWORD, 'Main')
    assert result == {'notes': 1, 'notes_to_update': 1, 'tags_to_add': 2, 'applied': False, 'synced': False}
    assert mutations(client) == []
    assert [a for a, _ in client.calls] == ['profile', 'notesInfo', 'cardsInfo']


def test_apply_is_additive_idempotent_and_sync_is_explicit(client, write):
    path = write()
    result = ti.import_tag_changes(path, PASSWORD, 'Main', apply=True)
    assert result['applied'] and not result['synced']
    assert set(client.notes[1]['tags']) == {'existing', '日本語::復習', 'new'}
    assert mutations(client) == ['addTags']
    client.calls.clear()
    result = ti.import_tag_changes(path, PASSWORD, 'Main', apply=True, sync=True)
    assert result['tags_to_add'] == 0 and result['synced']
    assert mutations(client) == ['sync']
    assert [a for a, _ in client.calls][-3:] == ['notesInfo', 'profile', 'sync']


@pytest.mark.parametrize('problem', ['profile', 'model', 'fields', 'card', 'missing', 'switch'])
def test_full_preflight_blocks_all_writes(client, write, problem):
    if problem == 'profile':
        client.profile = 'Other'
    elif problem == 'model':
        client.notes[2]['modelName'] = 'Changed'
    elif problem == 'fields':
        client.notes[2]['fields']['Front']['value'] = '日本語'  # Sanitized display text is not raw identity.
    elif problem == 'card':
        client.cards[12]['note'] = 1
    elif problem == 'missing':
        client.notes[2]['noteId'] = 3
    else:
        client.switch_after_preflight = True
    with pytest.raises(ti.TagImportError):
        ti.import_tag_changes(write(package([change(), change(2, 12)])), PASSWORD, 'Main', apply=True, sync=True)
    assert mutations(client) == []


def test_partial_failure_is_safe_to_retry_and_never_syncs(client, write):
    path = write(package([change(), change(2, 12)]))
    client.fail_note = 2
    with pytest.raises(ti.TagImportError, match='Some additions may already be saved') as error:
        ti.import_tag_changes(path, PASSWORD, 'Main', apply=True, sync=True)
    assert 'secret' not in str(error.value)
    assert 'sync' not in mutations(client)
    assert 'new' in client.notes[1]['tags']
    client.calls.clear()
    client.fail_note = None
    result = ti.import_tag_changes(path, PASSWORD, 'Main', apply=True, sync=True)
    assert result['notes_to_update'] == 1
    assert mutations(client) == ['addTags', 'sync']


def test_verify_failure_never_syncs(client, write):
    client.ignore_add = True
    with pytest.raises(ti.TagImportError):
        ti.import_tag_changes(write(), PASSWORD, 'Main', apply=True, sync=True)
    assert mutations(client) == ['addTags']


def test_sync_requires_apply_before_read_or_connect(tmp_path):
    with pytest.raises(ti.TagImportError, match='requires'):
        ti.import_tag_changes(tmp_path / 'missing', PASSWORD, 'Main', sync=True)


@pytest.mark.parametrize('endpoint', ['https://example.com', 'http://127.0.0.1:8765/secret',
                                     'http://user:password@localhost:8765', 'http://localhost:8765?token=x'])
def test_remote_or_credential_endpoints_refused(endpoint):
    with pytest.raises(ConnectorError):
        AnkiConnect(endpoint)


@pytest.mark.parametrize('mode', ['wrong_password', 'tamper', 'symlink', 'oversize', 'invalid_json'])
def test_envelope_failures_before_connect(client, write, tmp_path, mode):
    path = write()
    password = PASSWORD
    if mode == 'wrong_password':
        password = 'another-wrong-test-password'
    elif mode == 'tamper':
        value = json.loads(path.read_text())
        value['ciphertext'] = ('A' if value['ciphertext'][0] != 'A' else 'B') + value['ciphertext'][1:]
        path.write_text(json.dumps(value))
    elif mode == 'symlink':
        link = tmp_path / 'link'
        link.symlink_to(path)
        path = link
    elif mode == 'oversize':
        with path.open('wb') as stream:
            stream.truncate(ti.MAX_PACKAGE_BYTES + 1)
    else:
        path.write_text('{broken')
    with pytest.raises(ti.TagImportError):
        ti.import_tag_changes(path, password, 'Main', apply=True)
    assert client.calls == []


@pytest.mark.parametrize('tag', ['has space', 'has\nnewline', 'wild*', 'wild?', '\ud800', '', 'a'*129, 'zero\u200bwidth'])
def test_invalid_tags(tag):
    value = package()
    value['changes'][0]['add_tags'] = [tag]
    with pytest.raises(ti.TagImportError):
        ti.validate_changes(value)


@pytest.mark.parametrize('mutation', [
    lambda v: v['changes'].append(copy.deepcopy(v['changes'][0])),
    lambda v: v['changes'][0]['card_ids'].append(11),
    lambda v: v['changes'][0].update(note_id=True),
    lambda v: v['changes'][0].update(note_id=2**53),
    lambda v: v['changes'][0].update(remove_tags=['existing']),
    lambda v: v['changes'][0].update(fingerprint='a'*63),
    lambda v: v.update(created_at='2026-01-01'),
    lambda v: v['source'].update(kind='remote'),
    lambda v: v['changes'][0].update(add_tags=['a']*101),
])
def test_invalid_contract(mutation):
    value = package()
    mutation(value)
    with pytest.raises(ti.TagImportError):
        ti.validate_changes(value)


def test_fingerprint_is_deterministic_and_tracks_raw_fields():
    assert note_fingerprint('Basic', {'b': '2', 'a': '日本語'}) == note_fingerprint('Basic', {'a': '日本語', 'b': '2'})
    assert note_fingerprint('Basic', {'a': '<b>x</b>'}) != note_fingerprint('Basic', {'a': 'x'})


def test_cli_defaults_to_dry_run_and_does_not_print_content(client, write, monkeypatch, capsys):
    monkeypatch.setenv('PAGES_PASSWORD', PASSWORD)
    assert ti.main([str(write()), '--profile', 'Main']) == 0
    output = capsys.readouterr().out
    assert json.loads(output)['applied'] is False
    assert PASSWORD not in output and '日本語' not in output
    assert mutations(client) == []


def test_ankiweb_source_binds_raw_identity_to_explicit_local_profile(client, write):
    value = package()
    value['source'] = {'kind': 'ankiweb', 'profile': 'AnkiWeb'}
    result = ti.import_tag_changes(write(value), PASSWORD, 'Main', apply=True)
    assert result['applied']
    assert mutations(client) == ['addTags']


def test_ankiweb_source_still_requires_expected_active_profile(client, write):
    value = package()
    value['source'] = {'kind': 'ankiweb', 'profile': 'AnkiWeb'}
    client.profile = 'Other'
    with pytest.raises(ti.TagImportError):
        ti.import_tag_changes(write(value), PASSWORD, 'Main', apply=True)
    assert mutations(client) == []


def test_local_source_profile_mismatch_rejected_before_contact(client, write):
    value = package()
    value['source']['profile'] = 'Other'
    with pytest.raises(ti.TagImportError):
        ti.import_tag_changes(write(value), PASSWORD, 'Main', apply=True)
    assert client.calls == []


def test_sync_failure_reports_uncertainty_even_when_tags_already_exist(client, write, monkeypatch):
    client.notes[1]['tags'] += ['日本語::復習', 'new']
    original = client.call
    def call(action, **params):
        if action == 'sync':
            raise ConnectorError('private remote sync failure')
        return original(action, **params)
    monkeypatch.setattr(client, 'call', call)
    with pytest.raises(ti.TagImportError, match='sync completion is not confirmed'):
        ti.import_tag_changes(write(), PASSWORD, 'Main', apply=True, sync=True)
    assert mutations(client) == []


def test_existing_case_variant_is_already_present_and_sync_can_finish(client, write):
    value = package()
    value['changes'][0]['add_tags'] = ['New', 'NEW']
    client.notes[1]['tags'] = ['existing', 'new']
    result = ti.import_tag_changes(write(value), PASSWORD, 'Main', apply=True, sync=True)
    assert result['tags_to_add'] == 0
    assert result['synced']
    assert mutations(client) == ['sync']
    assert client.notes[1]['tags'] == ['existing', 'new']


def test_anki_case_canonicalization_verifies_and_retry_is_idempotent(client, write, monkeypatch):
    value = package()
    value['changes'][0]['add_tags'] = ['NEWTAG', 'newtag']
    original = client.call
    def call(action, **params):
        if action == 'addTags':
            # Model Anki's existing registry spelling for both old/new tags.
            result = original(action, **params)
            client.notes[1]['tags'] = [tag.title() for tag in client.notes[1]['tags']]
            return result
        return original(action, **params)
    monkeypatch.setattr(client, 'call', call)
    path = write(value)
    result = ti.import_tag_changes(path, PASSWORD, 'Main', apply=True, sync=True)
    assert result['tags_to_add'] == 1
    assert result['synced']
    assert set(client.notes[1]['tags']) == {'Existing', 'Newtag'}
    client.calls.clear()
    again = ti.import_tag_changes(path, PASSWORD, 'Main', apply=True, sync=True)
    assert again['tags_to_add'] == 0
    assert mutations(client) == ['sync']
