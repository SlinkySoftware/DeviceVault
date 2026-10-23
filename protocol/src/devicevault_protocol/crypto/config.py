"""
Configuration loader for DeviceVault encryption.

All settings come from environment variables (each also accepts ``<NAME>_FILE``):

    DV_ENCRYPTION_ENABLED                   true/false (default false)
    DV_ENCRYPTION_KEYS                      kid=<base64 32-byte key>,kid2=<...>
    DV_ENCRYPTION_DEFAULT_KID               KID used for new encryptions
    DV_ENCRYPTION_CHUNK_SIZE                streaming chunk size in bytes
    DV_ENCRYPTION_ALLOW_PLAINTEXT_FALLBACK  true/false (default true)

Copyright (C) 2026, Slinky Software
License: GPLv3+
"""

import logging

from devicevault_protocol.crypto.constants import (
    DEFAULT_CHUNK_SIZE,
    ENV_ALLOW_PLAINTEXT_FALLBACK,
    ENV_CHUNK_SIZE,
    ENV_DEFAULT_KID,
    ENV_ENCRYPTION_ENABLED,
    ENV_KEYS,
    MAX_CHUNK_SIZE,
    MIN_CHUNK_SIZE,
)
from devicevault_protocol.crypto.exceptions import KeyProviderError
from devicevault_protocol.crypto.providers import KeyProvider, LocalKeyProvider
from devicevault_protocol.env import ConfigError, env_bool, env_int, env_map, env_str

logger = logging.getLogger('devicevault.crypto.config')

# Module-level singleton
_key_provider: KeyProvider | None = None


def get_encryption_enabled() -> bool:
    """Return whether encryption is enabled."""
    return env_bool(ENV_ENCRYPTION_ENABLED, False)


def get_chunk_size() -> int:
    """Return the configured chunk size in bytes, clamped to the valid range."""
    chunk_size = env_int(ENV_CHUNK_SIZE, DEFAULT_CHUNK_SIZE)
    return max(MIN_CHUNK_SIZE, min(chunk_size, MAX_CHUNK_SIZE))


def get_allow_plaintext_fallback() -> bool:
    """Return whether plaintext writes are allowed when encryption is disabled."""
    return env_bool(ENV_ALLOW_PLAINTEXT_FALLBACK, True)


def get_key_provider(force: bool = False) -> KeyProvider | None:
    """Return the configured KeyProvider singleton (lazy initialised).

    Args:
        force: If ``True``, attempt to load keys even when encryption is
            disabled.  This is used by the storage worker to support
            per-device encryption — the device's ``encrypt_backups`` flag
            controls whether encryption is actually applied, not the global
            switch.

    Returns:
        ``None`` if no valid key material is available (or encryption is
        disabled and *force* is ``False``).

    Raises:
        KeyProviderError: If encryption is enabled and keys are missing or
            invalid (fail closed).
    """
    global _key_provider

    if _key_provider is not None:
        return _key_provider

    if not force and not get_encryption_enabled():
        logger.info('Encryption is disabled — no key provider initialised')
        return None

    try:
        keys = env_map(ENV_KEYS)
    except ConfigError as exc:
        if force:
            logger.warning('Master keys are malformed — per-device encryption unavailable: %s', exc)
            return None
        raise KeyProviderError(str(exc)) from exc

    if not keys:
        if force:
            logger.info('No master keys configured — per-device encryption unavailable')
            return None
        raise KeyProviderError(f'Encryption is enabled but {ENV_KEYS} is not set')

    try:
        _key_provider = LocalKeyProvider(keys=keys, default_kid=env_str(ENV_DEFAULT_KID))
    except KeyProviderError:
        if force:
            logger.warning('Master keys configured but invalid — per-device encryption unavailable')
            return None
        raise

    return _key_provider


def reset_singletons() -> None:
    """Reset cached singletons (for testing)."""
    global _key_provider
    _key_provider = None
