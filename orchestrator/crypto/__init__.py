"""
DeviceVault Backup Encryption Module
=====================================

Provides transparent envelope encryption for backup data at rest using
AES-256-GCM authenticated encryption with streaming chunked processing.

Architecture overview:
    - **KeyProvider**: Interface for master key management (Local or KMS).
    - **Header codec**: Binary header prepended to every encrypted object.
    - **EncryptingWriter / DecryptingReader**: Streaming chunk-based I/O.
    - **CryptoStorage**: Transparent wrapper around any storage driver.

Security references:
    - AES-256-GCM: NIST SP 800-38D (Galois/Counter Mode)
    - AES Key Wrap: RFC 3394 / NIST SP 800-38F
    - Key management: NIST SP 800-57 Part 1 Rev 5

Copyright (C) 2026, Slinky Software
License: GPLv3+
"""

from crypto.providers import KeyProvider, LocalKeyProvider
from crypto.header import EncryptionHeader, HEADER_MAGIC
from crypto.engine import encrypt_backup, decrypt_backup
from crypto.wrapper import CryptoStorage

__all__ = [
    'KeyProvider',
    'LocalKeyProvider',
    'EncryptionHeader',
    'HEADER_MAGIC',
    'encrypt_backup',
    'decrypt_backup',
    'CryptoStorage',
]
