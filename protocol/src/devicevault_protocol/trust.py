"""Verification of orchestrator-signed task payloads."""

from typing import Any

from devicevault_protocol.identity import pinned_orchestrator_key
from devicevault_protocol.signing import SignatureError
from devicevault_protocol.tasks import verify_task

__all__ = ['SignatureError', 'verified_payload']


def verified_payload(envelope: Any) -> dict[str, Any]:
    """The task parameters, if signed by the orchestrator this process pinned.

    Raises SignatureError otherwise; such tasks must be rejected, not retried.
    """
    return verify_task(envelope, pinned_orchestrator_key())
