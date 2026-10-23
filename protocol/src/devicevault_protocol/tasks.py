"""Signing and verification of orchestrator -> worker Celery task payloads.

Tasks carry a single argument: a signed envelope (see ``signing``) whose
payload is the task's parameters. Workers verify it against the orchestrator
key they pinned at registration.
"""

from typing import Any

from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey, Ed25519PublicKey

from devicevault_protocol import signing

ORCHESTRATOR_SIGNER = 'orchestrator'


def sign_task(payload: dict[str, Any], key: Ed25519PrivateKey) -> dict[str, Any]:
    return signing.sign(payload, key, ORCHESTRATOR_SIGNER)


def verify_task(envelope: Any, orchestrator_key: Ed25519PublicKey | None) -> dict[str, Any]:
    if orchestrator_key is None:
        raise signing.SignatureError('this worker has not been assigned by an orchestrator yet')
    if isinstance(envelope, dict) and envelope.get('signer') != ORCHESTRATOR_SIGNER:
        raise signing.SignatureError('task was not signed by the orchestrator')
    return signing.verify(envelope, orchestrator_key)
