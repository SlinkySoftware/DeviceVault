"""
DeviceVault encryption header codec.

Binary header layout (prepended to every encrypted backup object)::

    Offset  Size    Field
    ──────  ──────  ─────────────────────
    0       4       Magic bytes: ``DVLT``
    4       1       enc_version (uint8)
    5       1       cipher_id_len (uint8)
    6       var     cipher_id (UTF-8, e.g. ``AES-256-GCM``)
    6+C     4       chunk_size (uint32 big-endian)
    10+C    1       kid_len (uint8)
    11+C    var     kid (UTF-8, master key identifier)
    11+C+K  2       edk_len (uint16 big-endian)
    13+C+K  var     edk (encrypted DEK bytes)
    13+C+K+E 2      aad_len (uint16 big-endian)
    15+C+K+E var    aad (JSON-encoded additional authenticated data)

After the header, the encrypted chunks follow immediately:
    For each chunk: [12-byte nonce][ciphertext][16-byte GCM tag]

The header is designed to be self-describing so that decryption requires
only access to the master key (via KID lookup).

Copyright (C) 2026, Slinky Software
License: GPLv3+
"""

import json
import struct
from dataclasses import dataclass, field
from typing import Any, Dict, Optional

from crypto.constants import (
    HEADER_MAGIC,
    ENC_VERSION,
    CIPHER_ID,
    DEFAULT_CHUNK_SIZE,
    GCM_NONCE_BYTES,
    GCM_TAG_BYTES,
)
from crypto.exceptions import HeaderError

# Re-export for convenience
__all__ = ['EncryptionHeader', 'HEADER_MAGIC']


@dataclass
class EncryptionHeader:
    """Parsed / constructed encryption header for a backup object."""

    enc_version: int = ENC_VERSION
    cipher: str = CIPHER_ID
    chunk_size: int = DEFAULT_CHUNK_SIZE
    kid: str = ''
    edk: bytes = b''
    aad: Dict[str, Any] = field(default_factory=dict)

    # ── Serialisation ───────────────────────────────────────────────────

    def to_bytes(self) -> bytes:
        """Encode this header to its binary wire format."""
        parts = []

        # Magic
        parts.append(HEADER_MAGIC)

        # enc_version (uint8)
        parts.append(struct.pack('!B', self.enc_version))

        # cipher_id
        cipher_bytes = self.cipher.encode('utf-8')
        if len(cipher_bytes) > 255:
            raise HeaderError('cipher identifier exceeds 255 bytes')
        parts.append(struct.pack('!B', len(cipher_bytes)))
        parts.append(cipher_bytes)

        # chunk_size (uint32)
        parts.append(struct.pack('!I', self.chunk_size))

        # kid
        kid_bytes = self.kid.encode('utf-8')
        if len(kid_bytes) > 255:
            raise HeaderError('KID exceeds 255 bytes')
        parts.append(struct.pack('!B', len(kid_bytes)))
        parts.append(kid_bytes)

        # edk
        if len(self.edk) > 65535:
            raise HeaderError('EDK exceeds 65535 bytes')
        parts.append(struct.pack('!H', len(self.edk)))
        parts.append(self.edk)

        # aad (JSON)
        aad_bytes = json.dumps(self.aad, separators=(',', ':')).encode('utf-8') if self.aad else b''
        if len(aad_bytes) > 65535:
            raise HeaderError('AAD exceeds 65535 bytes')
        parts.append(struct.pack('!H', len(aad_bytes)))
        parts.append(aad_bytes)

        return b''.join(parts)

    @classmethod
    def from_bytes(cls, data: bytes, offset: int = 0) -> 'EncryptionHeader':
        """Parse a header from *data* starting at *offset*.

        Also sets ``header_size`` on the returned object indicating how
        many bytes the header consumed.
        """
        pos = offset

        # Magic
        if data[pos:pos + 4] != HEADER_MAGIC:
            raise HeaderError('Invalid magic bytes — not a DeviceVault encrypted object')
        pos += 4

        # enc_version
        enc_version = struct.unpack_from('!B', data, pos)[0]
        pos += 1

        # cipher_id
        cipher_len = struct.unpack_from('!B', data, pos)[0]
        pos += 1
        cipher = data[pos:pos + cipher_len].decode('utf-8')
        pos += cipher_len

        # chunk_size
        chunk_size = struct.unpack_from('!I', data, pos)[0]
        pos += 4

        # kid
        kid_len = struct.unpack_from('!B', data, pos)[0]
        pos += 1
        kid = data[pos:pos + kid_len].decode('utf-8')
        pos += kid_len

        # edk
        edk_len = struct.unpack_from('!H', data, pos)[0]
        pos += 2
        edk = bytes(data[pos:pos + edk_len])
        pos += edk_len

        # aad
        aad_len = struct.unpack_from('!H', data, pos)[0]
        pos += 2
        if aad_len:
            aad = json.loads(data[pos:pos + aad_len].decode('utf-8'))
        else:
            aad = {}
        pos += aad_len

        hdr = cls(
            enc_version=enc_version,
            cipher=cipher,
            chunk_size=chunk_size,
            kid=kid,
            edk=edk,
            aad=aad,
        )
        # Attach the total header size so callers know where chunks start
        hdr.header_size = pos - offset
        return hdr

    @property
    def chunk_overhead(self) -> int:
        """Bytes of overhead per encrypted chunk (nonce + GCM tag)."""
        return GCM_NONCE_BYTES + GCM_TAG_BYTES


def is_encrypted(data: bytes) -> bool:
    """Quick check whether *data* starts with the DeviceVault encryption header."""
    return len(data) >= 4 and data[:4] == HEADER_MAGIC
