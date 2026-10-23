import base64
import hashlib
from datetime import UTC, datetime, timedelta

import pytest

from devicevault_protocol import signing
from devicevault_protocol.tasks import sign_task, verify_task


@pytest.fixture
def key():
    return signing.generate_signing_key()


def test_round_trip(key):
    envelope = signing.sign({'a': 1, 'b': [1, 2]}, key, 'worker-1')

    assert signing.verify(envelope, key.public_key()) == {'a': 1, 'b': [1, 2]}


def test_envelope_survives_json_round_trip(key):
    import json

    envelope = json.loads(json.dumps(signing.sign({'ünicode': 'ä', 'n': 1}, key, 'w')))

    assert signing.verify(envelope, key.public_key()) == {'ünicode': 'ä', 'n': 1}


@pytest.mark.parametrize(
    'tamper',
    [
        lambda e: e['payload'].update(queues=['evil']),
        lambda e: e.update(signer='someone-else'),
        lambda e: e.update(issued_at='2099-01-01T00:00:00+00:00'),
        lambda e: e.update(sig=signing.b64encode(b'\0' * 64)),
    ],
)
def test_any_tampering_breaks_the_signature(key, tamper):
    envelope = signing.sign({'queues': ['ok']}, key, 'orchestrator')
    tamper(envelope)

    with pytest.raises(signing.SignatureError):
        signing.verify(envelope, key.public_key())


def test_wrong_key_is_rejected(key):
    envelope = signing.sign({'a': 1}, key, 'w')

    with pytest.raises(signing.SignatureError):
        signing.verify(envelope, signing.generate_signing_key().public_key())


def test_expired_envelopes_are_rejected(key):
    envelope = signing.sign({'a': 1}, key, 'w', now=datetime.now(UTC) - timedelta(hours=1))

    with pytest.raises(signing.SignatureError, match='expired'):
        signing.verify(envelope, key.public_key(), max_age=timedelta(minutes=15))
    assert signing.verify(envelope, key.public_key()) == {'a': 1}


@pytest.mark.parametrize('envelope', [None, 'x', {}, {'v': 1, 'payload': {}}, {'v': 2, 'payload': {}, 'sig': 'x'}])
def test_malformed_envelopes_are_rejected(key, envelope):
    with pytest.raises(signing.SignatureError):
        signing.verify(envelope, key.public_key())


def test_keys_round_trip_through_base64(key):
    restored = signing.private_key_from_b64(signing.private_key_to_b64(key))

    assert signing.public_key_to_b64(restored) == signing.public_key_to_b64(key)


def test_fingerprint_is_ssh_style_sha256(key):
    public = signing.public_key_to_b64(key)
    expected = base64.b64encode(hashlib.sha256(base64.b64decode(public)).digest()).decode().rstrip('=')

    assert signing.fingerprint(public) == f'SHA256:{expected}'


def test_tasks_must_be_signed_by_the_orchestrator(key):
    envelope = sign_task({'device_id': 1}, key)

    assert verify_task(envelope, key.public_key()) == {'device_id': 1}
    with pytest.raises(signing.SignatureError, match='not been assigned'):
        verify_task(envelope, None)
    with pytest.raises(signing.SignatureError, match='orchestrator'):
        verify_task(signing.sign({'device_id': 1}, key, 'a-worker'), key.public_key())
