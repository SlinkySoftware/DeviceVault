"""
DeviceVault payload encryption.

- Backup content: AES-256-GCM in chunks (the ``DVLT`` format, see ``header``
  and ``engine``) under a fresh key per backup. Collectors wrap that key to
  the orchestrator's vault public key (``providers.VaultPublicKey``); only
  the orchestrator's vault key ring (``providers.VaultKeyRing``) unwraps it.
- Secrets sent to workers (credentials, storage config): sealed to the
  recipient worker's X25519 key (``ecies.seal``).

Security references:
    - AES-256-GCM: NIST SP 800-38D (Galois/Counter Mode)
    - AES Key Wrap: RFC 3394 / NIST SP 800-38F
    - X25519: RFC 7748; HKDF: RFC 5869
    - Key management: NIST SP 800-57 Part 1 Rev 5

Copyright (C) 2026, Slinky Software
License: GPLv3+
"""

from devicevault_protocol.crypto.ecies import seal, unseal
from devicevault_protocol.crypto.engine import decrypt_backup, encrypt_backup, encrypt_stream
from devicevault_protocol.crypto.header import HEADER_MAGIC, EncryptionHeader, is_encrypted
from devicevault_protocol.crypto.providers import KeyProvider, VaultKeyRing, VaultPublicKey

__all__ = [
    'HEADER_MAGIC',
    'EncryptionHeader',
    'KeyProvider',
    'VaultKeyRing',
    'VaultPublicKey',
    'decrypt_backup',
    'encrypt_backup',
    'encrypt_stream',
    'is_encrypted',
    'seal',
    'unseal',
]
