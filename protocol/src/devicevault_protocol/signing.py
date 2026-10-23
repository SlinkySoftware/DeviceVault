"""Ed25519-signed message envelopes.

Every orchestrator -> worker message (assignments and tasks) and every
worker -> orchestrator event is wrapped in an envelope::

    {"v": 1, "signer": "<id>", "issued_at": "<iso8601>", "payload": {...}, "sig": "<base64>"}

The signature covers the canonical JSON of everything except ``sig``, so the
signer and timestamp cannot be swapped onto another payload.
"""

import base64
import hashlib
import json
from datetime import UTC, datetime, timedelta
from typing import Any

from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey, Ed25519PublicKey
from cryptography.hazmat.primitives.serialization import Encoding, NoEncryption, PrivateFormat, PublicFormat

ENVELOPE_VERSION = 1


class SignatureError(ValueError):
    """The envelope is malformed, expired, or not signed by the expected key."""


def b64encode(data: bytes) -> str:
    return base64.b64encode(data).decode('ascii')


def b64decode(data: str) -> bytes:
    try:
        return base64.b64decode(data, validate=True)
    except (ValueError, TypeError) as exc:
        raise SignatureError('invalid base64') from exc


def generate_signing_key() -> Ed25519PrivateKey:
    return Ed25519PrivateKey.generate()


def private_key_to_b64(key: Ed25519PrivateKey) -> str:
    return b64encode(key.private_bytes(Encoding.Raw, PrivateFormat.Raw, NoEncryption()))


def private_key_from_b64(value: str) -> Ed25519PrivateKey:
    raw = b64decode(value.strip())
    if len(raw) != 32:
        raise SignatureError('an Ed25519 private key is 32 bytes')
    return Ed25519PrivateKey.from_private_bytes(raw)


def public_key_to_b64(key: Ed25519PublicKey | Ed25519PrivateKey) -> str:
    public = key.public_key() if isinstance(key, Ed25519PrivateKey) else key
    return b64encode(public.public_bytes(Encoding.Raw, PublicFormat.Raw))


def public_key_from_b64(value: str) -> Ed25519PublicKey:
    raw = b64decode(value)
    if len(raw) != 32:
        raise SignatureError('an Ed25519 public key is 32 bytes')
    return Ed25519PublicKey.from_public_bytes(raw)


def fingerprint(public_key_b64: str) -> str:
    """SSH-style fingerprint of a raw public key: ``SHA256:<base64 without padding>``."""
    digest = hashlib.sha256(b64decode(public_key_b64)).digest()
    return 'SHA256:' + base64.b64encode(digest).decode('ascii').rstrip('=')


def _canonical(document: dict[str, Any]) -> bytes:
    return json.dumps(document, sort_keys=True, separators=(',', ':'), ensure_ascii=False).encode('utf-8')


def sign(
    payload: dict[str, Any], key: Ed25519PrivateKey, signer: str, *, now: datetime | None = None
) -> dict[str, Any]:
    envelope = {
        'v': ENVELOPE_VERSION,
        'signer': signer,
        'issued_at': (now or datetime.now(UTC)).isoformat(),
        'payload': payload,
    }
    envelope['sig'] = b64encode(key.sign(_canonical(envelope)))
    return envelope


def peek(envelope: Any) -> dict[str, Any]:
    """Return the payload WITHOUT verifying it (only to find out who claims to have signed it)."""
    if not isinstance(envelope, dict) or not isinstance(envelope.get('payload'), dict):
        raise SignatureError('not a signed envelope')
    return envelope['payload']


def verify(envelope: Any, public_key: Ed25519PublicKey, *, max_age: timedelta | None = None) -> dict[str, Any]:
    """Return the payload if ``envelope`` is validly signed by ``public_key``."""
    if not isinstance(envelope, dict):
        raise SignatureError('not a signed envelope')
    if envelope.get('v') != ENVELOPE_VERSION:
        raise SignatureError(f'unsupported envelope version {envelope.get("v")!r}')
    signature = envelope.get('sig')
    if not isinstance(signature, str):
        raise SignatureError('missing signature')
    unsigned = {k: v for k, v in envelope.items() if k != 'sig'}
    try:
        public_key.verify(b64decode(signature), _canonical(unsigned))
    except InvalidSignature as exc:
        raise SignatureError('signature does not match') from exc

    if max_age is not None:
        try:
            issued = datetime.fromisoformat(envelope['issued_at'])
        except (KeyError, TypeError, ValueError) as exc:
            raise SignatureError('missing or invalid issued_at') from exc
        if datetime.now(UTC) - issued > max_age:
            raise SignatureError('envelope has expired')

    payload = envelope.get('payload')
    if not isinstance(payload, dict):
        raise SignatureError('payload must be an object')
    return payload
