import pytest

from chatgpt_crypto import EnvelopeError, new_keypair, open_envelope, seal


def test_round_trip_and_randomized_ciphertext():
    private, public = new_keypair()
    message = {"query": "化学", "request_id": "example"}
    first = seal(message, public)
    assert open_envelope(first, private) == message
    assert seal(message, public) != first


def test_wrong_key_tampering_and_invalid_inputs_fail():
    private, public = new_keypair()
    other, _ = new_keypair()
    envelope = seal({"text": "private"}, public)
    with pytest.raises(EnvelopeError):
        open_envelope(envelope, other)
    with pytest.raises(EnvelopeError):
        open_envelope({**envelope, "version": True}, private)
    with pytest.raises(EnvelopeError):
        open_envelope({**envelope, "nonce": "AAAA"}, private)
    with pytest.raises(EnvelopeError):
        seal({"text": "x" * 33000}, public)
    with pytest.raises(EnvelopeError):
        seal({}, "invalid")
