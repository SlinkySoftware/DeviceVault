"""The orchestrator's signing key (DV_SIGNING_KEY).

Every assignment and task sent to workers is signed with it, and workers pin
its public key when first approved, so all orchestrator nodes must share the
same key and it must not change. Generate one with
``manage.py generate_signing_key``.
"""

from functools import cache
from typing import Any

from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from django.conf import settings
from django.core.exceptions import ImproperlyConfigured

from devicevault_protocol import signing
from devicevault_protocol.tasks import sign_task as _sign_task


@cache
def signing_key() -> Ed25519PrivateKey:
    value = settings.DEVICEVAULT_SIGNING_KEY
    if not value:
        raise ImproperlyConfigured('DV_SIGNING_KEY must be set (generate one with manage.py generate_signing_key)')
    try:
        return signing.private_key_from_b64(value)
    except signing.SignatureError as exc:
        raise ImproperlyConfigured(f'DV_SIGNING_KEY is not a valid key: {exc}') from exc


def public_key() -> str:
    return signing.public_key_to_b64(signing_key())


def fingerprint() -> str:
    return signing.fingerprint(public_key())


def sign_task(payload: dict[str, Any]) -> dict[str, Any]:
    """Wrap task parameters in an envelope workers will accept."""
    return _sign_task(payload, signing_key())
