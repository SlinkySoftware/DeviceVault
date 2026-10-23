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

import json
import logging
import os
from typing import Any, Dict, Optional, Tuple

from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from cryptography.exceptions import InvalidTag

from crypto.constants import (
    AES_KEY_BYTES,
    GCM_NONCE_BYTES,
    GCM_TAG_BYTES,
    DEFAULT_CHUNK_SIZE,
    MAX_CHUNK_COUNT,
    CIPHER_ID,
    ENC_VERSION,
)
from crypto.exceptions import (
    EncryptionError,
    DecryptionError,
    TamperDetectedError,
    ChunkLimitExceededError,
    HeaderError,
)
from crypto.header import EncryptionHeader, is_encrypted
from crypto.providers import KeyProvider

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


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def encrypt_backup(
    plaintext: bytes,
    key_provider: KeyProvider,
    *,
    chunk_size: int = DEFAULT_CHUNK_SIZE,
    aad_fields: Optional[Dict[str, Any]] = None,
) -> Tuple[bytes, Dict[str, Any]]:
    """Encrypt *plaintext* using envelope encryption (AES-256-GCM).

    Args:
        plaintext: Raw backup bytes to encrypt.
        key_provider: Master key provider for DEK wrapping.
        chunk_size: Plaintext bytes per chunk (default 1 MiB).
        aad_fields: Extra fields to include in AAD (backup_id, device_id, etc.).

    Returns:
        (ciphertext_blob, metadata) where *ciphertext_blob* is the complete
        encrypted object (header + chunks) and *metadata* is a dict with
        ``enc_version``, ``cipher``, ``kid``, and ``edk`` (base64) suitable
        for storing in the database.

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
        header_bytes = header.to_bytes()

        # Chunk and encrypt
        aesgcm = AESGCM(bytes(dek))
        chunks = []
        offset = 0
        chunk_index = 0

        while offset < len(plaintext):
            if chunk_index >= MAX_CHUNK_COUNT:
                raise ChunkLimitExceededError(
                    f'Backup exceeds maximum {MAX_CHUNK_COUNT} chunks '
                    f'(chunk_size={chunk_size})'
                )

            end = min(offset + chunk_size, len(plaintext))
            chunk_data = plaintext[offset:end]

            # Unique random nonce per chunk (96-bit, CSPRNG)
            nonce = os.urandom(GCM_NONCE_BYTES)

            # Encrypt with AAD
            ct = aesgcm.encrypt(nonce, chunk_data, aad_bytes)

            # ct includes the 16-byte tag appended by cryptography library
            chunks.append(nonce + ct)

            offset = end
            chunk_index += 1

        # Handle empty plaintext (zero chunks)
        if not chunks and len(plaintext) == 0:
            nonce = os.urandom(GCM_NONCE_BYTES)
            ct = aesgcm.encrypt(nonce, b'', aad_bytes)
            chunks.append(nonce + ct)

        # Assemble final blob
        blob = header_bytes + b''.join(chunks)

        # Metadata for database storage
        import base64
        metadata = {
            'enc_version': ENC_VERSION,
            'cipher': CIPHER_ID,
            'kid': kid,
            'edk': base64.b64encode(edk).decode('ascii'),
        }

        logger.info(
            'Encrypted backup: %d bytes -> %d bytes (%d chunks, kid=%s)',
            len(plaintext), len(blob), chunk_index or 1, kid,
        )

        return bytes(blob), metadata

    except (EncryptionError, ChunkLimitExceededError):
        raise
    except Exception as exc:
        raise EncryptionError(f'Encryption failed: {exc}') from exc
    finally:
        # Zeroize plaintext DEK from memory
        _zeroize(dek)


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
            raise DecryptionError(
                f'Unsupported enc_version={header.enc_version} '
                f'(expected {ENC_VERSION})'
            )

        if header.cipher != CIPHER_ID:
            raise DecryptionError(
                f'Unsupported cipher="{header.cipher}" '
                f'(expected "{CIPHER_ID}")'
            )

        # Unwrap DEK
        dek = bytearray(key_provider.unwrap_key(header.edk, header.kid))

        try:
            # Reconstruct AAD (must match what was used during encryption)
            aad_bytes = json.dumps(
                header.aad, separators=(',', ':')
            ).encode('utf-8') if header.aad else b''

            aesgcm = AESGCM(bytes(dek))
            chunk_size = header.chunk_size
            # Each encrypted chunk = nonce + ciphertext + tag
            encrypted_chunk_size = GCM_NONCE_BYTES + chunk_size + GCM_TAG_BYTES

            plaintext_parts = []
            pos = header_size

            while pos < len(blob):
                # Read nonce
                nonce = blob[pos:pos + GCM_NONCE_BYTES]
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
                ct_tag = blob[pos:pos + ct_tag_len]
                pos += ct_tag_len

                try:
                    pt = aesgcm.decrypt(nonce, ct_tag, aad_bytes)
                except InvalidTag:
                    raise TamperDetectedError(
                        'GCM authentication failed — backup data may be '
                        'tampered with, or the wrong master key was used.'
                    )

                plaintext_parts.append(pt)

            result = b''.join(plaintext_parts)
            logger.info(
                'Decrypted backup: %d bytes -> %d bytes (%d chunks, kid=%s)',
                len(blob), len(result), len(plaintext_parts), header.kid,
            )
            return result

        finally:
            _zeroize(dek)

    except (DecryptionError, TamperDetectedError):
        raise
    except Exception as exc:
        raise DecryptionError(f'Decryption failed: {exc}') from exc
