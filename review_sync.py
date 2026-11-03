"""Apply a single compare-before-write review through Anki's scheduler."""
import hashlib
import json
import re
import uuid

from anki import scheduler_pb2, sync_pb2
from cloud_sync import DEFAULT_ENDPOINT, _validate_endpoint
from cloud_tags import CloudTagError, TagConflict, _download, _normal_sync
from note_identity import note_fingerprint


def review_version(col, cid):
    row = col.db.first('select id,nid,did,ord,type,queue,due,ivl,factor,reps,lapses,left,odue,odid,flags,data from cards where id=?', cid)
    if row is None:
        raise TagConflict('Card no longer exists.')
    note = col.get_note(row[1])
    model = note.note_type()
    if model is None:
        raise TagConflict('Note type no longer exists.')
    last = col.db.scalar('select max(id) from revlog where cid=?', cid)
    value = [row, last, note_fingerprint(model['name'], dict(note.items()))]
    return hashlib.sha256(json.dumps(value, ensure_ascii=False, separators=(',', ':')).encode()).hexdigest()


def validate_review(value):
    if not isinstance(value, dict) or set(value) != {'format', 'version', 'request_id', 'card_id', 'review_version', 'rating'}:
        raise ValueError('Invalid review request.')
    try:
        valid_id = str(uuid.UUID(value['request_id'])) == value['request_id']
    except (ValueError, TypeError, AttributeError):
        valid_id = False
    if (value['format'] != 'anki-atlas-review' or type(value['version']) is not int or value['version'] != 1
            or not valid_id or type(value['card_id']) is not int or not 0 < value['card_id'] < 2**53
            or not isinstance(value['review_version'], str) or re.fullmatch('[a-f0-9]{64}', value['review_version']) is None
            or value['rating'] not in ('again', 'hard', 'good', 'easy')):
        raise ValueError('Invalid review request.')
    return value


def apply_review(value, hkey, endpoint=None, *, _test_endpoint=None):
    validate_review(value)
    if not isinstance(hkey, str) or not hkey or len(hkey) > 4096 or any(not 33 <= ord(c) <= 126 for c in hkey):
        raise CloudTagError('Set a valid AnkiWeb sync token.')
    destination = _validate_endpoint(_test_endpoint or endpoint or DEFAULT_ENDPOINT, test_local_only=_test_endpoint is not None)
    auth = sync_pb2.SyncAuth(hkey=hkey, endpoint=destination, io_timeout_secs=60)
    cid = value['card_id']
    with _download(auth, test_local_only=_test_endpoint is not None) as col:
        _normal_sync(col, auth, test_endpoint=_test_endpoint)
        card = col.get_card(cid)
        if card.queue not in (0, 1, 2, 3, 4) or review_version(col, cid) != value['review_version']:
            raise TagConflict('Card state changed; refresh before reviewing.')
        rating = {'again': scheduler_pb2.CardAnswer.AGAIN, 'hard': scheduler_pb2.CardAnswer.HARD,
                  'good': scheduler_pb2.CardAnswer.GOOD, 'easy': scheduler_pb2.CardAnswer.EASY}[value['rating']]
        before = set(r[0] for r in col.db.all('select id from revlog where cid=?', cid))
        card.start_timer()
        answer = col.sched.build_answer(card=card, states=col._backend.get_scheduling_states(cid), rating=rating)
        col.sched.answer_card(answer)
        rows = col.db.all('select id,cid,ease,ivl,lastIvl,factor,time,type from revlog where cid=?', cid)
        added = [r for r in rows if r[0] not in before]
        if len(added) != 1:
            raise CloudTagError('Review log could not be identified.')
        expected = added[0]
        after = review_version(col, cid)
        _normal_sync(col, auth, test_endpoint=_test_endpoint)
    with _download(auth, test_local_only=_test_endpoint is not None) as check:
        actual = check.db.first('select id,cid,ease,ivl,lastIvl,factor,time,type from revlog where id=?', expected[0])
        if actual != expected or review_version(check, cid) != after:
            raise CloudTagError('Review could not be verified; do not retry automatically.')
    return {'verified': True}
