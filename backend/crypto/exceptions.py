"""
Exception hierarchy for the DeviceVault crypto module.

Copyright (C) 2026, Slinky Software
License: GPLv3+
"""


class CryptoError(Exception):
    """Base exception for all crypto-related errors."""


class KeyProviderError(CryptoError):
    """Raised when the key provider cannot be initialised or used."""


class MasterKeyNotFoundError(KeyProviderError):
    """Raised when a requested KID is not in the key ring."""


class KeyUnwrapError(KeyProviderError):
    """Raised when DEK unwrapping fails (wrong key, corrupted EDK)."""


class EncryptionError(CryptoError):
    """Raised when encryption of backup data fails."""


class DecryptionError(CryptoError):
    """Raised when decryption of backup data fails."""


class HeaderError(CryptoError):
    """Raised when the encryption header is malformed or invalid."""


class TamperDetectedError(DecryptionError):
    """Raised when GCM authentication fails (data integrity violation)."""


class ChunkLimitExceededError(EncryptionError):
    """Raised when backup data exceeds the maximum allowed chunk count."""
