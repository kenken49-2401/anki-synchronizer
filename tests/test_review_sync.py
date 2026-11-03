import uuid
import pytest
from anki import scheduler_pb2
from cloud_tags import TagConflict
from review_sync import apply_review, review_version, validate_review
from test_cloud_tags import official


@pytest.mark.parametrize('rating,ease', [('again', 1), ('hard', 2), ('good', 3), ('easy', 4)])
def test_official_sync_records_rating_once_and_rejects_replay(official, rating, ease):
    phone, notes, auth, endpoint, _ = official
    cid = notes[1].cards()[0].id
    request = {'format': 'anki-atlas-review', 'version': 1, 'request_id': str(uuid.uuid4()),
               'card_id': int(cid), 'review_version': review_version(phone, cid), 'rating': rating}
    assert apply_review(request, auth.hkey, _test_endpoint=endpoint) == {'verified': True}
    with pytest.raises(TagConflict):
        apply_review(request, auth.hkey, _test_endpoint=endpoint)
    phone.sync_collection(auth, sync_media=False)
    assert phone.db.list('select ease from revlog where cid=?', cid) == [ease]


def test_changed_card_rejected(official):
    phone, notes, auth, endpoint, _ = official
    card = notes[1].cards()[0]
    request = {'format': 'anki-atlas-review', 'version': 1, 'request_id': str(uuid.uuid4()),
               'card_id': int(card.id), 'review_version': review_version(phone, card.id), 'rating': 'good'}
    card.start_timer()
    answer = phone.sched.build_answer(card=card, states=phone._backend.get_scheduling_states(card.id), rating=scheduler_pb2.CardAnswer.GOOD)
    phone.sched.answer_card(answer)
    phone.sync_collection(auth, sync_media=False)
    with pytest.raises(TagConflict):
        apply_review(request, auth.hkey, _test_endpoint=endpoint)
    assert len(phone.db.list('select id from revlog where cid=?', card.id)) == 1


def test_invalid_review_rejected():
    with pytest.raises(ValueError):
        validate_review({'format': 'anki-atlas-review'})
