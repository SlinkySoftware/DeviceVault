"""
Cryptographic constants and configuration defaults.

All values here align with ASD-approved algorithms and NIST guidance:
    - AES-256-GCM: NIST SP 800-38D
    - 96-bit nonces: NIST recommended IV length for GCM
    - AES Key Wrap: RFC 3394 / NIST SP 800-38F
    - X25519 + HKDF-SHA256 for wrapping to public keys (RFC 7748, RFC 5869)

Copyright (C) 2026, Slinky Software
License: GPLv3+
"""

# ---------------------------------------------------------------------------
# Header / format identifiers
# ---------------------------------------------------------------------------
HEADER_MAGIC = b'DVLT'  # 4-byte magic identifying encrypted objects
ENC_VERSION = 1  # Current encryption format version
CIPHER_ID = 'AES-256-GCM'  # Cipher identifier stored in header

# ---------------------------------------------------------------------------
# AES-256-GCM parameters
# ---------------------------------------------------------------------------
AES_KEY_BITS = 256  # AES key size in bits
AES_KEY_BYTES = AES_KEY_BITS // 8  # 32 bytes
GCM_NONCE_BYTES = 12  # 96-bit nonce (NIST SP 800-38D recommended)
GCM_TAG_BYTES = 16  # 128-bit authentication tag

# ---------------------------------------------------------------------------
# Streaming / chunking
# ---------------------------------------------------------------------------
DEFAULT_CHUNK_SIZE = 1 * 1024 * 1024  # 1 MiB per chunk (default)
MIN_CHUNK_SIZE = 64 * 1024  # 64 KiB minimum
MAX_CHUNK_SIZE = 8 * 1024 * 1024  # 8 MiB maximum
MAX_CHUNK_COUNT = 2**32  # Safety limit: reject > 2^32 chunks
