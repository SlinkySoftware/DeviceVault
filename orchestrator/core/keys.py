"""The orchestrator's encryption keys, besides the signing key (see core.signing).

- Data keys (``DV_DATA_KEYS``, always required): AES-256-GCM keys that encrypt
  secrets at rest in the database (credentials, storage target settings). A key ring
  ``kid=<base64>,...``; the first key encrypts, any key in the ring decrypts.
- Vault keys (``DV_VAULT_KEYS``, required when ``DV_PAYLOAD_ENCRYPTION`` is
  on): X25519 private keys. Collectors encrypt backups to the current vault
  public key; only the orchestrator can decrypt them.

Generate both with ``manage.py generate_keys``. Every orchestrator node must
share them, and a key must stay in its ring while anything encrypted with it
remains.
"""

import json
import os
from functools import cache
from typing import Any

from cryptography.exceptions import InvalidTag
from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from django.conf import settings
from django.core.exceptions import ImproperlyConfigured

from devicevault_protocol.crypto import VaultKeyRing, seal
from devicevault_protocol.crypto.constants import AES_KEY_BYTES, GCM_NONCE_BYTES
from devicevault_protocol.crypto.ecies import public_key_from_b64
from devicevault_protocol.crypto.exceptions import CryptoError, KeyProviderError
from devicevault_protocol.crypto.providers import parse_key_ring
from devicevault_protocol.signing import b64decode, b64encode

# Stored form of an encrypted value: "dv1:<kid>:<base64 nonce + ciphertext>".
_PREFIX = 'dv1'


@cache
def data_keys() -> tuple[str, dict[str, AESGCM]]:
    """``(current_kid, {kid: cipher})``."""
    try:
        ring = parse_key_ring(settings.DEVICEVAULT_DATA_KEYS, 'DV_DATA_KEYS')
        if not ring:
            raise KeyProviderError('DV_DATA_KEYS must be set (generate one with manage.py generate_keys)')
        ciphers = {}
        for kid, value in ring.items():
            if ':' in kid:
                raise KeyProviderError(f'DV_DATA_KEYS: key id "{kid}" must not contain ":"')
            raw = b64decode(value)
            if len(raw) != AES_KEY_BYTES:
                raise KeyProviderError(f'DV_DATA_KEYS: key "{kid}" must be {AES_KEY_BYTES} bytes')
            ciphers[kid] = AESGCM(raw)
    except (KeyProviderError, ValueError) as exc:
        raise ImproperlyConfigured(str(exc)) from exc
    return next(iter(ciphers)), ciphers


def encrypt_value(value: Any, *, context: str) -> str:
    """Encrypt JSON ``value``; ``context`` (e.g. the field) binds it to where it is stored."""
    kid, ciphers = data_keys()
    nonce = os.urandom(GCM_NONCE_BYTES)
    ciphertext = ciphers[kid].encrypt(nonce, json.dumps(value).encode('utf-8'), context.encode('utf-8'))
    return f'{_PREFIX}:{kid}:{b64encode(nonce + ciphertext)}'


def decrypt_value(stored: str, *, context: str) -> Any:
    prefix, _, rest = stored.partition(':')
    kid, _, payload = rest.partition(':')
    if prefix != _PREFIX or not payload:
        raise CryptoError('not an encrypted value')
    ciphers = data_keys()[1]
    if kid not in ciphers:
        raise ImproperlyConfigured(f'data key "{kid}" is not in DV_DATA_KEYS')
    raw = b64decode(payload)
    try:
        plaintext = ciphers[kid].decrypt(raw[:GCM_NONCE_BYTES], raw[GCM_NONCE_BYTES:], context.encode('utf-8'))
    except InvalidTag as exc:
        raise CryptoError(f'encrypted value for {context} failed authentication') from exc
    return json.loads(plaintext)


# --- payload encryption ------------------------------------------------------------


def payload_encryption() -> bool:
    return settings.DEVICEVAULT_PAYLOAD_ENCRYPTION


@cache
def vault() -> VaultKeyRing:
    if not settings.DEVICEVAULT_VAULT_KEYS:
        raise ImproperlyConfigured('DV_VAULT_KEYS must be set (generate one with manage.py generate_keys)')
    try:
        return VaultKeyRing.from_config(settings.DEVICEVAULT_VAULT_KEYS)
    except KeyProviderError as exc:
        raise ImproperlyConfigured(str(exc)) from exc


def vault_public() -> dict[str, str] | None:
    """What collect tasks carry so collectors encrypt backups, or None when payload encryption is off."""
    if not payload_encryption():
        return None
    ring = vault()
    return {'kid': ring.current_kid, 'public_key': ring.public_key_b64()}


def for_workers(value: Any, workers) -> dict[str, str]:
    """``value`` sealed to each worker's encryption key, keyed by worker id."""
    return {str(worker.pk): seal(value, public_key_from_b64(worker.encryption_key)) for worker in workers}


def add_secret(spec: dict[str, Any], name: str, value: Any, workers) -> None:
    """Put ``value`` in a task spec: sealed per worker as ``<name>_sealed``, or plain when payload encryption is off.

    The worker side is ``devicevault_worker.payload.secret`` (receivers: ``devicevault_receiver.config``).
    """
    if payload_encryption():
        spec[f'{name}_sealed'] = for_workers(value, workers)
    else:
        spec[name] = value
