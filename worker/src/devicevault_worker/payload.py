"""What the orchestrator encrypts for workers, and what collectors encrypt for it.

With payload encryption on (``DV_PAYLOAD_ENCRYPTION`` on the orchestrator),
each collect task carries the vault public key, and secrets arrive sealed to
this worker's X25519 key, one copy per eligible worker. With it off, both
travel in plaintext so developers can inspect queues and Redis.
"""

from typing import Any

from devicevault_protocol.crypto import VaultPublicKey, encrypt_backup, unseal
from devicevault_protocol.crypto.exceptions import CryptoError
from devicevault_worker.app import identity
from devicevault_worker.drivers.base import PermanentError


def prepare(content: bytes, job: dict[str, Any]) -> tuple[bytes, bool]:
    """Return the bytes to stage and whether they are encrypted."""
    vault = job.get('encryption')
    if not vault:
        return content, False
    try:
        provider = VaultPublicKey(vault['kid'], vault['public_key'])
        aad = {'job_id': job['job_id'], 'device_id': job['device']['id']}
        blob, _ = encrypt_backup(content, provider, aad_fields=aad)
    except (CryptoError, KeyError, TypeError) as exc:
        raise PermanentError(f'could not encrypt the backup: {exc}') from exc
    return blob, True


def secret(spec: dict[str, Any], name: str) -> Any:
    """``spec[name]``, or this worker's copy of ``spec[name + "_sealed"]``."""
    sealed = spec.get(f'{name}_sealed')
    if sealed is None:
        return spec.get(name)
    mine = sealed.get(identity.worker_id)
    if mine is None:
        raise PermanentError(f'the {name} were not sealed for this worker; was it approved after the job was queued?')
    try:
        return unseal(mine, identity.encryption_key)
    except CryptoError as exc:
        raise PermanentError(f'could not open the {name}: {exc}') from exc
