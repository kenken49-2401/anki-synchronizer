"""Owner-approved, compare-before-write edits to existing Anki note fields.

Only the original or already-applied complete note is accepted. Native Anki
updates retain existing card IDs and review history; templates are never edited.
"""
from datetime import datetime
import re

from note_identity import note_fingerprint
from tag_import import _id, _text


class NoteEditError(ValueError):
    """Fixed messages only: no private field contents in diagnostics."""


def validate_note_changes(value):
    def invalid():
        raise NoteEditError("Invalid note-change package.")
    if (not isinstance(value, dict) or set(value) != {'format', 'version', 'created_at', 'source', 'changes'}
            or value['format'] != 'anki-atlas-note-changes' or type(value['version']) is not int or value['version'] != 1):
        invalid()
    try:
        if not _text(value['created_at'], 64) or datetime.fromisoformat(value['created_at'].replace('Z', '+00:00')).tzinfo is None:
            invalid()
    except (ValueError, TypeError):
        invalid()
    source = value['source']
    if (not isinstance(source, dict) or set(source) != {'kind', 'profile'}
            or source['kind'] not in ('ankiweb', 'ankiconnect') or not _text(source['profile'], 256, nonempty=True)):
        invalid()
    changes = value['changes']
    if not isinstance(changes, list) or not 1 <= len(changes) <= 500:
        invalid()
    notes, cards = set(), set()
    for change in changes:
        if (not isinstance(change, dict) or set(change) != {'note_id', 'card_ids', 'model', 'fingerprint', 'fields', 'set_fields'}
                or not _id(change['note_id']) or change['note_id'] in notes
                or not _text(change['model'], 256, nonempty=True)
                or not isinstance(change['fingerprint'], str) or re.fullmatch('[a-f0-9]{64}', change['fingerprint']) is None):
            invalid()
        notes.add(change['note_id'])
        ids = change['card_ids']
        if not isinstance(ids, list) or not 1 <= len(ids) <= 50000:
            invalid()
        for cid in ids:
            if not _id(cid) or cid in cards or len(cards) >= 50000:
                invalid()
            cards.add(cid)
        fields, updates = change['fields'], change['set_fields']
        if (not isinstance(fields, dict) or not 1 <= len(fields) <= 64
                or any(not _text(k, 256, nonempty=True) or not _text(v, 128000) for k, v in fields.items())
                or not isinstance(updates, dict) or not 1 <= len(updates) <= len(fields)
                or any(k not in fields or not _text(v, 128000) or v == fields[k] for k, v in updates.items())
                or note_fingerprint(change['model'], fields) != change['fingerprint']):
            invalid()
    return value


def desired_fields(change):
    return {**change['fields'], **change['set_fields']}


def _preflight(col, changes, *, applied=False):
    from cloud_tags import TagConflict
    notes = {}
    try:
        for change in changes:
            note = col.get_note(change['note_id'])
            model = note.note_type()
            actual, desired = dict(note.items()), desired_fields(change)
            if (model is None or model['name'] != change['model']
                    or any(int(col.get_card(cid).nid) != change['note_id'] for cid in change['card_ids'])
                    or actual != desired and (applied or actual != change['fields'])):
                raise TagConflict("Note text changed; refresh and submit the edit again.")
            notes[change['note_id']] = (note, actual != desired)
    except TagConflict:
        raise
    except Exception:
        raise TagConflict("Note identity changed; refresh and submit the edit again.") from None
    return notes


def apply_cloud_note_changes(package, hkey, endpoint=None, *, _test_endpoint=None):
    from anki import sync_pb2
    from cloud_sync import DEFAULT_ENDPOINT, _validate_endpoint
    from cloud_tags import _download, _normal_sync, CloudTagError, TagConflict
    validate_note_changes(package)
    if not isinstance(hkey, str) or not hkey or len(hkey) > 4096 or any(not 33 <= ord(c) <= 126 for c in hkey):
        raise CloudTagError("Set a valid AnkiWeb sync token.")
    try:
        destination = _validate_endpoint(_test_endpoint or endpoint or DEFAULT_ENDPOINT, test_local_only=_test_endpoint is not None)
        auth = sync_pb2.SyncAuth(hkey=hkey, endpoint=destination, io_timeout_secs=60)
        changes = package['changes']
        with _download(auth, test_local_only=_test_endpoint is not None) as col:
            _normal_sync(col, auth, test_endpoint=_test_endpoint)
            notes = _preflight(col, changes)
            original_tags = {nid: {t.lower() for t in note.tags} for nid, (note, _) in notes.items()}
            count = sum(pending for _, pending in notes.values())
            for change in changes:
                note, pending = notes[change['note_id']]
                if pending:
                    for name, value in change['set_fields'].items():
                        note[name] = value
                    col.update_note(note)
            _preflight(col, changes, applied=True)
            if count:
                _normal_sync(col, auth, test_endpoint=_test_endpoint)
        with _download(auth, test_local_only=_test_endpoint is not None) as verified:
            notes = _preflight(verified, changes, applied=True)
            if any(not tags <= {t.lower() for t in notes[nid][0].tags} for nid, tags in original_tags.items()):
                raise CloudTagError("Remote edit verification failed; the request remains pending.")
        return {'notes': len(changes), 'notes_updated': count, 'verified': True}
    except (CloudTagError, TagConflict):
        raise
    except Exception:
        raise CloudTagError("Note sync did not finish or could not be verified. Check Anki before retrying.") from None
