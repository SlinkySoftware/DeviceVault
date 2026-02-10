"""
CryptoStorage — transparent encryption wrapper around storage drivers.

This wrapper implements the same interface as ``fs.store_backup`` /
``fs.read_backup`` (and ``git.*``) so it can be dropped in as a
decorator around any storage backend.  It intercepts write and read
calls to encrypt and decrypt backup data transparently.

Usage in the storage task pipeline::

    from crypto.wrapper import CryptoStorage

    crypto = CryptoStorage(key_provider, chunk_size=1_048_576)
    # Wrap a store call
    storage_ref, enc_meta = crypto.store(
        content, rel_path, config, is_binary,
        store_fn=fs_storage.store_backup,
        aad_fields={'device_id': 42},
    )
    # Wrap a read call
    content = crypto.read(
        storage_ref, config, is_binary,
        read_fn=fs_storage.read_backup,
    )

Copyright (C) 2026, Slinky Software
License: GPLv3+
"""

import base64
import logging
from typing import Any, Callable, Dict, Optional, Tuple, Union

from crypto.constants import DEFAULT_CHUNK_SIZE
from crypto.engine import encrypt_backup, decrypt_backup
from crypto.header import is_encrypted
from crypto.providers import KeyProvider

logger = logging.getLogger('devicevault.crypto.wrapper')


class CryptoStorage:
    """Transparent encryption layer sitting between the task pipeline and
    the storage driver.

    The collection worker and consumers remain unchanged — they write / read
    through this wrapper which handles envelope encryption internally.
    """

    def __init__(
        self,
        key_provider: KeyProvider,
        chunk_size: int = DEFAULT_CHUNK_SIZE,
        encryption_enabled: bool = True,
    ):
        self._key_provider = key_provider
        self._chunk_size = chunk_size
        self._encryption_enabled = encryption_enabled

    @property
    def encryption_enabled(self) -> bool:
        return self._encryption_enabled

    # ── Write path ──────────────────────────────────────────────────────

    def store(
        self,
        content: Union[str, bytes],
        rel_path: str,
        config: Dict,
        is_binary: bool,
        store_fn: Callable,
        aad_fields: Optional[Dict[str, Any]] = None,
    ) -> Tuple[str, Optional[Dict[str, Any]]]:
        """Encrypt *content* then delegate to *store_fn*.

        Returns:
            (storage_ref, encryption_metadata) — metadata is ``None`` when
            encryption is disabled.
        """
        if not self._encryption_enabled:
            storage_ref = store_fn(content, rel_path, config, is_binary=is_binary)
            return storage_ref, None

        # Normalise content to bytes
        if isinstance(content, str):
            raw_bytes = content.encode('utf-8')
        else:
            raw_bytes = content

        # Encrypt
        blob, enc_meta = encrypt_backup(
            raw_bytes,
            self._key_provider,
            chunk_size=self._chunk_size,
            aad_fields=aad_fields,
        )

        # Store the encrypted blob as binary (always binary on disk)
        storage_ref = store_fn(blob, rel_path, config, is_binary=True)

        logger.info(
            'CryptoStorage.store: encrypted %d bytes -> %d bytes, ref=%s, kid=%s',
            len(raw_bytes), len(blob), storage_ref, enc_meta.get('kid'),
        )

        return storage_ref, enc_meta

    # ── Read path ───────────────────────────────────────────────────────

    def read(
        self,
        storage_ref: str,
        config: Dict,
        is_binary: bool,
        read_fn: Callable,
    ) -> Union[str, bytes]:
        """Read from storage and decrypt if the object is encrypted.

        Backward compatible: plaintext (v0) objects are returned as-is.
        """
        # Always read as binary so we can inspect the header
        raw = read_fn(storage_ref, config, is_binary=True)

        if not isinstance(raw, bytes):
            # If the driver returned a string, it's plaintext
            return raw

        if not is_encrypted(raw):
            # v0 plaintext — return as-is
            if is_binary:
                return raw
            return raw.decode('utf-8')

        # Decrypt
        plaintext = decrypt_backup(raw, self._key_provider)

        if is_binary:
            return plaintext
        return plaintext.decode('utf-8')
