"""
Cryptographic constants and configuration defaults.

All values here align with ASD-approved algorithms and NIST guidance:
    - AES-256-GCM: NIST SP 800-38D
    - 96-bit nonces: NIST recommended IV length for GCM
    - AES Key Wrap: RFC 3394 / NIST SP 800-38F

Copyright (C) 2026, Slinky Software
License: GPLv3+
"""

# ---------------------------------------------------------------------------
# Header / format identifiers
# ---------------------------------------------------------------------------
HEADER_MAGIC = b'DVLT'          # 4-byte magic identifying encrypted objects
ENC_VERSION = 1                 # Current encryption format version
CIPHER_ID = 'AES-256-GCM'      # Cipher identifier stored in header

# ---------------------------------------------------------------------------
# AES-256-GCM parameters
# ---------------------------------------------------------------------------
AES_KEY_BITS = 256              # AES key size in bits
AES_KEY_BYTES = AES_KEY_BITS // 8  # 32 bytes
GCM_NONCE_BYTES = 12            # 96-bit nonce (NIST SP 800-38D recommended)
GCM_TAG_BYTES = 16              # 128-bit authentication tag

# ---------------------------------------------------------------------------
# Streaming / chunking
# ---------------------------------------------------------------------------
DEFAULT_CHUNK_SIZE = 1 * 1024 * 1024  # 1 MiB per chunk (default)
MIN_CHUNK_SIZE = 64 * 1024            # 64 KiB minimum
MAX_CHUNK_SIZE = 8 * 1024 * 1024      # 8 MiB maximum
MAX_CHUNK_COUNT = 2 ** 32             # Safety limit: reject > 2^32 chunks

# ---------------------------------------------------------------------------
# Key provider identifiers
# ---------------------------------------------------------------------------
PROVIDER_LOCAL = 'local'
PROVIDER_KMS = 'kms'

# ---------------------------------------------------------------------------
# Configuration keys (config.yaml / env vars)
# ---------------------------------------------------------------------------
CFG_ENCRYPTION_ENABLED = 'ENCRYPTION_ENABLED'
CFG_CHUNK_SIZE = 'CHUNK_SIZE_BYTES'
CFG_KEY_PROVIDER = 'KEY_PROVIDER'
CFG_LOCAL_MASTER_KEY = 'LOCAL_MASTER_KEY'
CFG_ALLOW_PLAINTEXT_FALLBACK = 'ALLOW_PLAINTEXT_FALLBACK'

ENV_ENCRYPTION_ENABLED = 'DEVICEVAULT_ENCRYPTION_ENABLED'
ENV_CHUNK_SIZE = 'DEVICEVAULT_CHUNK_SIZE_BYTES'
ENV_KEY_PROVIDER = 'DEVICEVAULT_KEY_PROVIDER'
ENV_LOCAL_MASTER_KEY = 'DEVICEVAULT_LOCAL_MASTER_KEY'
ENV_ALLOW_PLAINTEXT_FALLBACK = 'DEVICEVAULT_ALLOW_PLAINTEXT_FALLBACK'
