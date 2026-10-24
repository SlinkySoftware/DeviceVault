"""
Streaming AES-256-GCM encryption and decryption engine.

Processes data in fixed-size chunks with a unique random 96-bit nonce per
chunk.  Uses constant memory regardless of backup size.

Encrypted object format:
    [Header][Chunk0][Chunk1]...[ChunkN]

Each chunk:
    [12-byte nonce][ciphertext + 16-byte GCM tag]

AAD (Additional Authenticated Data) is bound to every chunk so that
tampering with any component — header, AAD, nonce, ciphertext, or tag —
is detected by GCM authentication.

Security references:
    - AES-256-GCM: NIST SP 800-38D
    - Nonce generation: CSPRNG via ``os.urandom`` (12 bytes per chunk)
    - Key zeroisation: ``_zeroize()`` helper overwrites memory

Copyright (C) 2026, Slinky Software
License: GPLv3+
"""

import base64
import io
import json
import logging
import os
from typing import Any, BinaryIO

from cryptography.exceptions import InvalidTag
from cryptography.hazmat.primitives.ciphers.aead import AESGCM

from devicevault_protocol.crypto.constants import (
    AES_KEY_BYTES,
    CIPHER_ID,
    DEFAULT_CHUNK_SIZE,
    ENC_VERSION,
    GCM_NONCE_BYTES,
    GCM_TAG_BYTES,
    MAX_CHUNK_COUNT,
)
from devicevault_protocol.crypto.exceptions import (
    ChunkLimitExceededError,
    DecryptionError,
    EncryptionError,
    KeyProviderError,
    TamperDetectedError,
)
from devicevault_protocol.crypto.header import EncryptionHeader, is_encrypted
from devicevault_protocol.crypto.providers import KeyProvider

logger = logging.getLogger('devicevault.crypto.engine')


# ---------------------------------------------------------------------------
# Memory zeroisation helper
# ---------------------------------------------------------------------------


def _zeroize(buf: bytearray) -> None:
    """Overwrite *buf* in-place with zeros.

    Best-effort memory zeroisation. Python's GC may still hold copies
    but this reduces the window of exposure for plaintext key material.
    """
    for i in range(len(buf)):
        buf[i] = 0


def _read_full(source: BinaryIO, size: int) -> bytes:
    """Up to *size* bytes, short only at the end: decryption relies on every chunk but the last being full."""
    parts = []
    remaining = size
    while remaining:
        part = source.read(remaining)
        if not part:
            break
        parts.append(part)
        remaining -= len(part)
    return b''.join(parts)


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def encrypt_stream(
    source: BinaryIO,
    sink: BinaryIO,
    key_provider: KeyProvider,
    *,
    chunk_size: int = DEFAULT_CHUNK_SIZE,
    aad_fields: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Encrypt *source* into *sink* using envelope encryption (AES-256-GCM).

    Reads and writes one chunk at a time, so memory use does not depend on
    the backup's size. The output is the same object ``encrypt_backup``
    returns (header + chunks).

    Args:
        source: Binary file with the plaintext, read from its current position.
        sink: Binary file the encrypted object is written to.
        key_provider: Master key provider for DEK wrapping.
        chunk_size: Plaintext bytes per chunk (default 1 MiB).
        aad_fields: Extra fields to include in AAD (backup_id, device_id, etc.).

    Returns:
        A dict with ``enc_version``, ``cipher``, ``kid``, and ``edk``
        (base64) suitable for storing in the database.

    Raises:
        EncryptionError: On any encryption failure.
        ChunkLimitExceededError: If plaintext exceeds max chunk count.
    """
    # Generate fresh DEK (Data Encryption Key)
    dek = bytearray(os.urandom(AES_KEY_BYTES))

    try:
        # Wrap DEK with master key
        edk, kid = key_provider.wrap_key(bytes(dek))

        # Build AAD JSON (bound to every chunk for tamper detection)
        aad_dict = {
            'enc_version': ENC_VERSION,
            'cipher': CIPHER_ID,
            'kid': kid,
        }
        if aad_fields:
            aad_dict.update(aad_fields)
        aad_bytes = json.dumps(aad_dict, separators=(',', ':')).encode('utf-8')

        # Build header
        header = EncryptionHeader(
            enc_version=ENC_VERSION,
            cipher=CIPHER_ID,
            chunk_size=chunk_size,
            kid=kid,
            edk=edk,
            aad=aad_dict,
        )
        sink.write(header.to_bytes())

        # Chunk and encrypt; empty plaintext still gets one (empty) chunk
        aesgcm = AESGCM(bytes(dek))
        chunk_index = 0
        plaintext_size = 0

        while True:
            chunk_data = _read_full(source, chunk_size)
            if not chunk_data and chunk_index:
                break
            if chunk_index >= MAX_CHUNK_COUNT:
                raise ChunkLimitExceededError(
                    f'Backup exceeds maximum {MAX_CHUNK_COUNT} chunks (chunk_size={chunk_size})'
                )

            # Unique random nonce per chunk (96-bit, CSPRNG)
            nonce = os.urandom(GCM_NONCE_BYTES)

            # Encrypt with AAD; ct includes the 16-byte tag appended by cryptography library
            ct = aesgcm.encrypt(nonce, chunk_data, aad_bytes)
            sink.write(nonce + ct)

            plaintext_size += len(chunk_data)
            chunk_index += 1
            if not chunk_data:
                break

        metadata = {
            'enc_version': ENC_VERSION,
            'cipher': CIPHER_ID,
            'kid': kid,
            'edk': base64.b64encode(edk).decode('ascii'),
        }

        logger.debug('Encrypted backup: %d bytes (%d chunks, kid=%s)', plaintext_size, chunk_index, kid)

        return metadata

    except EncryptionError, ChunkLimitExceededError:
        raise
    except Exception as exc:
        raise EncryptionError(f'Encryption failed: {exc}') from exc
    finally:
        # Zeroize plaintext DEK from memory
        _zeroize(dek)


def encrypt_backup(
    plaintext: bytes,
    key_provider: KeyProvider,
    *,
    chunk_size: int = DEFAULT_CHUNK_SIZE,
    aad_fields: dict[str, Any] | None = None,
) -> tuple[bytes, dict[str, Any]]:
    """Encrypt *plaintext* in memory; see ``encrypt_stream``.

    Returns:
        (ciphertext_blob, metadata) where *ciphertext_blob* is the complete
        encrypted object (header + chunks).
    """
    sink = io.BytesIO()
    metadata = encrypt_stream(io.BytesIO(plaintext), sink, key_provider, chunk_size=chunk_size, aad_fields=aad_fields)
    return sink.getvalue(), metadata


def decrypt_backup(
    blob: bytes,
    key_provider: KeyProvider,
) -> bytes:
    """Decrypt a DeviceVault encrypted backup object.

    Handles:
        - v0 (plaintext legacy): returned as-is if no header magic present
        - v1 (AES-256-GCM chunked): full decryption

    Args:
        blob: Complete encrypted object (header + chunks) or plaintext.
        key_provider: Master key provider for DEK unwrapping.

    Returns:
        Decrypted plaintext bytes.

    Raises:
        DecryptionError: On any decryption failure.
        TamperDetectedError: If GCM authentication fails.
    """
    # Backward compatibility: if no magic header, treat as plaintext (v0)
    if not is_encrypted(blob):
        logger.debug('No encryption header detected — returning as plaintext (v0)')
        return blob

    try:
        # Parse header
        header = EncryptionHeader.from_bytes(blob)
        header_size = header.header_size

        if header.enc_version != ENC_VERSION:
            raise DecryptionError(f'Unsupported enc_version={header.enc_version} (expected {ENC_VERSION})')

        if header.cipher != CIPHER_ID:
            raise DecryptionError(f'Unsupported cipher="{header.cipher}" (expected "{CIPHER_ID}")')

        # Unwrap DEK
        dek = bytearray(key_provider.unwrap_key(header.edk, header.kid))

        try:
            # Reconstruct AAD (must match what was used during encryption)
            aad_bytes = json.dumps(header.aad, separators=(',', ':')).encode('utf-8') if header.aad else b''

            aesgcm = AESGCM(bytes(dek))
            chunk_size = header.chunk_size

            plaintext_parts = []
            pos = header_size

            while pos < len(blob):
                # Read nonce
                nonce = blob[pos : pos + GCM_NONCE_BYTES]
                if len(nonce) < GCM_NONCE_BYTES:
                    raise DecryptionError('Truncated chunk: nonce incomplete')
                pos += GCM_NONCE_BYTES

                # Remaining bytes for this chunk (ciphertext + tag)
                # The last chunk may be smaller than chunk_size
                remaining = len(blob) - pos
                # ciphertext+tag is at least GCM_TAG_BYTES
                if remaining < GCM_TAG_BYTES:
                    raise DecryptionError('Truncated chunk: ciphertext+tag incomplete')

                # Determine chunk ciphertext+tag length
                # If there's enough data for a full chunk, read chunk_size + tag
                # Otherwise, read whatever remains (last chunk)
                max_ct_tag = chunk_size + GCM_TAG_BYTES
                ct_tag_len = min(remaining, max_ct_tag)
                ct_tag = blob[pos : pos + ct_tag_len]
                pos += ct_tag_len

                try:
                    pt = aesgcm.decrypt(nonce, ct_tag, aad_bytes)
                except InvalidTag as exc:
                    raise TamperDetectedError(
                        'GCM authentication failed — backup data may be '
                        'tampered with, or the wrong master key was used.'
                    ) from exc

                plaintext_parts.append(pt)

            result = b''.join(plaintext_parts)
            logger.debug(
                'Decrypted backup: %d bytes -> %d bytes (%d chunks, kid=%s)',
                len(blob),
                len(result),
                len(plaintext_parts),
                header.kid,
            )
            return result

        finally:
            _zeroize(dek)

    except DecryptionError, KeyProviderError:
        raise
    except Exception as exc:
        raise DecryptionError(f'Decryption failed: {exc}') from exc
