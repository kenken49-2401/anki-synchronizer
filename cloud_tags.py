"""Apply owner-approved tag additions with Anki's incremental sync protocol.

Every run starts from AnkiWeb. Full uploads, media sync, deletion and card
answers are never used. The read-only Pages exporter remains independent.
"""
from __future__ import annotations

from contextlib import contextmanager
from pathlib import Path
import tempfile

from anki import sync_pb2
from anki.collection import Collection

from cloud_sync import DEFAULT_ENDPOINT, MAX_COLLECTION_BYTES, _validate_endpoint, CloudSyncError, resolve_download_endpoint
from note_identity import note_fingerprint
from tag_import import validate_changes


class CloudTagError(ValueError):
    """A fixed, non-private error; an uncertain sync may be retried safely."""


class TagConflict(CloudTagError):
    """The submitted note no longer matches AnkiWeb; do not apply it."""


@contextmanager
def _download(auth, *, test_local_only=False):
    with tempfile.TemporaryDirectory(prefix="anki-tags-") as directory:
        col = None
        try:
            path = Path(directory) / "collection.anki2"
            col = Collection(str(path))
            resolve_download_endpoint(col, auth, test_local_only=test_local_only)
            col.close_for_full_sync()
            col._backend.full_upload_or_download(
                sync_pb2.FullUploadOrDownloadRequest(auth=auth, upload=False))
            col.reopen(after_full_sync=True)
            if path.stat().st_size > MAX_COLLECTION_BYTES:
                raise CloudTagError("AnkiWeb collection exceeds the supported size.")
            yield col
        finally:
            if col is not None:
                try:
                    col.close()
                finally:
                    try:
                        col._backend.close_collection(downgrade_to_schema11=False)
                    except Exception:
                        pass


def _normal_sync(col, auth, *, test_endpoint=None):
    result = col.sync_collection(auth, sync_media=False)
    if result.required not in (result.NO_CHANGES, result.NORMAL_SYNC):
        raise CloudTagError("Full collection sync is required. Resolve it in Anki; no full upload was attempted.")
    if result.new_endpoint:
        if test_endpoint is not None:
            if result.new_endpoint.rstrip('/') != test_endpoint.rstrip('/'):
                raise CloudTagError("Unsupported sync destination.")
        else:
            _validate_endpoint(result.new_endpoint)
        auth.endpoint = result.new_endpoint


def _preflight(col, changes):
    notes, pending = {}, {}
    try:
        for change in changes:
            note = col.get_note(change['note_id'])
            model = note.note_type()
            if (model is None or model['name'] != change['model']
                    or note_fingerprint(model['name'], dict(note.items())) != change['fingerprint']
                    or any(int(col.get_card(cid).nid) != change['note_id'] for cid in change['card_ids'])):
                raise TagConflict("Note identity changed; refresh and submit the tags again.")
            seen = {t.lower() for t in note.tags}
            additions = []
            for tag in change['add_tags']:
                if tag.lower() not in seen:
                    additions.append(tag)
                    seen.add(tag.lower())
            notes[change['note_id']] = note
            pending[change['note_id']] = additions
    except TagConflict:
        raise
    except Exception:
        raise TagConflict("Note identity changed; refresh and submit the tags again.") from None
    return notes, pending


def apply_cloud_changes(package, hkey, endpoint=None, *, _test_endpoint=None):
    """Preflight every note, add tags, incremental sync, independently verify.

    A phone should sync before submitting and avoid editing the same note during
    this operation. Anki's normal conflict resolution applies to concurrent edits.
    """
    validate_changes(package)
    if not isinstance(hkey, str) or not hkey or len(hkey) > 4096 or any(not 33 <= ord(c) <= 126 for c in hkey):
        raise CloudTagError("Set a valid AnkiWeb sync token.")
    try:
        destination = _validate_endpoint(_test_endpoint or endpoint or DEFAULT_ENDPOINT,
                                         test_local_only=_test_endpoint is not None)
    except CloudSyncError:
        raise CloudTagError("Unsupported AnkiWeb sync destination.") from None
    auth = sync_pb2.SyncAuth(hkey=hkey, endpoint=destination, io_timeout_secs=60)
    changes = package['changes']
    if not changes:
        return {'notes': 0, 'tags_added': 0, 'verified': True}
    try:
        with _download(auth, test_local_only=_test_endpoint is not None) as col:
            # Finish a clean sync before editing, to include the phone's latest work.
            _normal_sync(col, auth, test_endpoint=_test_endpoint)
            notes, pending = _preflight(col, changes)
            original = {nid: {t.lower() for t in note.tags} for nid, note in notes.items()}
            count = sum(map(len, pending.values()))
            if count:
                for nid, tags in pending.items():
                    if tags:
                        col.tags.bulk_add([nid], ' '.join(tags))
                # Anki must only have changed tags; fields/types still match.
                _preflight(col, changes)
                _normal_sync(col, auth, test_endpoint=_test_endpoint)
        # A completed sync response alone is insufficient to acknowledge a queue item.
        with _download(auth, test_local_only=_test_endpoint is not None) as verified:
            notes, missing = _preflight(verified, changes)
            if any(missing.values()) or any(not tags <= {t.lower() for t in notes[nid].tags}
                                           for nid, tags in original.items()):
                raise CloudTagError("Remote tag verification failed; the request remains pending.")
        return {'notes': len(changes), 'tags_added': count, 'verified': True}
    except (CloudTagError, TagConflict):
        raise
    except Exception:
        raise CloudTagError("Tag sync did not finish or could not be verified. Retry after checking Anki.") from None
