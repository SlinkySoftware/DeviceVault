"""
Key Provider interface and implementations for master key management.

Supports a key ring with multiple active KIDs for read operations during
master key rotation. New writes always use the default KID.

Security notes:
    - Master keys are loaded once and held in memory for the process lifetime.
    - Plaintext DEKs are never persisted or logged.
    - AES Key Wrap (RFC 3394) is used to wrap/unwrap DEKs.

Copyright (C) 2026, Slinky Software
License: GPLv3+
"""

import base64
import logging
import os
from abc import ABC, abstractmethod
from typing import Dict, List, Optional, Tuple

from cryptography.hazmat.primitives.keywrap import (
    aes_key_wrap,
    aes_key_unwrap,
    InvalidUnwrap,
)

from crypto.constants import AES_KEY_BYTES
from crypto.exceptions import (
    KeyProviderError,
    MasterKeyNotFoundError,
    KeyUnwrapError,
)

logger = logging.getLogger('devicevault.crypto.providers')


class KeyProvider(ABC):
    """Abstract interface for master key management.

    Implementations must support a key ring (multiple KIDs) to enable
    seamless master key rotation. Reads can use any KID in the ring;
    writes always use the default KID.
    """

    @abstractmethod
    def get_default_key_id(self) -> str:
        """Return the KID used for new encryption operations."""

    @abstractmethod
    def wrap_key(self, plaintext_dek: bytes) -> Tuple[bytes, str]:
        """Wrap a plaintext DEK with the default master key.

        Returns:
            (encrypted_dek, kid) tuple.
        """

    @abstractmethod
    def unwrap_key(self, encrypted_dek: bytes, kid: str) -> bytes:
        """Unwrap an encrypted DEK using the master key identified by *kid*.

        Raises:
            MasterKeyNotFoundError: If *kid* is not in the key ring.
            KeyUnwrapError: If unwrapping fails (wrong key, corrupted EDK).
        """

    @abstractmethod
    def list_key_ids(self) -> List[str]:
        """Return all KIDs currently available in the key ring."""

    @abstractmethod
    def set_default_key_id(self, kid: str) -> None:
        """Switch the default KID for future wrap operations.

        Raises:
            MasterKeyNotFoundError: If *kid* is not in the key ring.
        """


class LocalKeyProvider(KeyProvider):
    """Key provider that reads master keys from local configuration.

    Supports multiple named keys in the key ring for rotation scenarios.
    Keys are base64-encoded 256-bit AES keys.

    Config structure (config.yaml ``encryption.keys`` section)::

        encryption:
          keys:
            mk-1: <base64-encoded-32-byte-key>
            mk-2: <base64-encoded-32-byte-key>
          default_key_id: mk-2

    Alternatively, a single key can be supplied via the
    ``DEVICEVAULT_LOCAL_MASTER_KEY`` environment variable (KID defaults
    to ``local-env``).
    """

    def __init__(self, keys: Optional[Dict[str, str]] = None, default_kid: Optional[str] = None):
        """Initialise the local key ring.

        Args:
            keys: Mapping of KID -> base64-encoded master key material.
            default_kid: KID to use for new wrap operations.
        """
        self._ring: Dict[str, bytes] = {}
        self._default_kid: Optional[str] = None

        # Load from explicit dict
        if keys:
            for kid, key_b64 in keys.items():
                self._add_key(kid, key_b64)

        # Fallback: single key from environment variable
        if not self._ring:
            env_key = os.environ.get('DEVICEVAULT_LOCAL_MASTER_KEY', '')
            if env_key:
                self._add_key('local-env', env_key)

        if not self._ring:
            raise KeyProviderError(
                'No master keys configured. Set encryption.keys in config.yaml '
                'or DEVICEVAULT_LOCAL_MASTER_KEY environment variable.'
            )

        # Set default KID
        if default_kid and default_kid in self._ring:
            self._default_kid = default_kid
        elif default_kid and default_kid not in self._ring:
            raise MasterKeyNotFoundError(f'Default KID "{default_kid}" not in key ring')
        else:
            # Use the last key added (or first if only one)
            self._default_kid = list(self._ring.keys())[-1]

        logger.info(
            'LocalKeyProvider initialised with %d key(s), default_kid=%s',
            len(self._ring), self._default_kid,
        )

    def _add_key(self, kid: str, key_b64: str) -> None:
        """Decode and validate a base64 master key."""
        try:
            raw = base64.b64decode(key_b64)
        except Exception as exc:
            raise KeyProviderError(f'Invalid base64 for KID "{kid}": {exc}') from exc

        if len(raw) != AES_KEY_BYTES:
            raise KeyProviderError(
                f'Master key "{kid}" must be {AES_KEY_BYTES} bytes, got {len(raw)}'
            )
        self._ring[kid] = raw

    # -- KeyProvider interface ------------------------------------------------

    def get_default_key_id(self) -> str:
        return self._default_kid

    def wrap_key(self, plaintext_dek: bytes) -> Tuple[bytes, str]:
        kid = self._default_kid
        master_key = self._ring[kid]
        edk = aes_key_wrap(master_key, plaintext_dek)
        logger.debug('Wrapped DEK with KID=%s (edk_len=%d)', kid, len(edk))
        return edk, kid

    def unwrap_key(self, encrypted_dek: bytes, kid: str) -> bytes:
        master_key = self._ring.get(kid)
        if master_key is None:
            raise MasterKeyNotFoundError(
                f'KID "{kid}" not found in key ring. '
                f'Available KIDs: {list(self._ring.keys())}'
            )
        try:
            dek = aes_key_unwrap(master_key, encrypted_dek)
        except InvalidUnwrap as exc:
            raise KeyUnwrapError(
                f'Failed to unwrap DEK with KID "{kid}". '
                'Key material may be corrupted or the wrong master key was used.'
            ) from exc
        logger.debug('Unwrapped DEK with KID=%s', kid)
        return dek

    def list_key_ids(self) -> List[str]:
        return list(self._ring.keys())

    def set_default_key_id(self, kid: str) -> None:
        if kid not in self._ring:
            raise MasterKeyNotFoundError(f'KID "{kid}" not in key ring')
        old = self._default_kid
        self._default_kid = kid
        logger.info('Switched default KID: %s -> %s', old, kid)

    @staticmethod
    def generate_master_key() -> str:
        """Generate a new random 256-bit master key, returned as base64."""
        raw = os.urandom(AES_KEY_BYTES)
        return base64.b64encode(raw).decode('ascii')
