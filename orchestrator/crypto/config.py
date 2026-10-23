"""
Configuration loader for DeviceVault encryption.

Reads encryption settings from config.yaml (``encryption`` section) and
environment variables.  Environment variables take precedence.

Configuration hierarchy (highest to lowest priority):
    1. Environment variables (DEVICEVAULT_*)
    2. config.yaml ``encryption`` section
    3. Built-in defaults

Copyright (C) 2026, Slinky Software
License: GPLv3+
"""

import logging
import os
from typing import Any, Dict, Optional, Tuple

from crypto.constants import (
    DEFAULT_CHUNK_SIZE,
    MIN_CHUNK_SIZE,
    MAX_CHUNK_SIZE,
    PROVIDER_LOCAL,
    ENV_ENCRYPTION_ENABLED,
    ENV_CHUNK_SIZE,
    ENV_KEY_PROVIDER,
    ENV_LOCAL_MASTER_KEY,
    ENV_ALLOW_PLAINTEXT_FALLBACK,
)
from crypto.providers import KeyProvider, LocalKeyProvider
from crypto.exceptions import CryptoError, KeyProviderError

logger = logging.getLogger('devicevault.crypto.config')

# Module-level singleton
_key_provider: Optional[KeyProvider] = None
_encryption_enabled: Optional[bool] = None
_chunk_size: Optional[int] = None
_allow_plaintext_fallback: Optional[bool] = None


def _parse_bool(val: Any) -> bool:
    """Parse a string/bool to boolean."""
    if isinstance(val, bool):
        return val
    if isinstance(val, str):
        return val.strip().lower() in ('true', '1', 'yes', 'on')
    return bool(val)


def _load_yaml_config() -> Dict:
    """Load the ``encryption`` section from config.yaml if available."""
    try:
        config_path = os.environ.get('DEVICEVAULT_CONFIG', '')
        if not config_path:
            # Try default path
            from pathlib import Path
            config_path = str(Path(__file__).resolve().parent.parent / 'config' / 'config.yaml')

        if os.path.exists(config_path):
            import yaml
            with open(config_path) as f:
                cfg = yaml.safe_load(f) or {}
            return cfg.get('encryption', {})
    except Exception as exc:
        logger.warning('Failed to load encryption config from YAML: %s', exc)
    return {}


def get_encryption_enabled(yaml_cfg: Optional[Dict] = None) -> bool:
    """Return whether encryption is enabled."""
    global _encryption_enabled
    if _encryption_enabled is not None:
        return _encryption_enabled

    if yaml_cfg is None:
        yaml_cfg = _load_yaml_config()

    # Env var takes precedence
    env_val = os.environ.get(ENV_ENCRYPTION_ENABLED)
    if env_val is not None:
        _encryption_enabled = _parse_bool(env_val)
    else:
        _encryption_enabled = _parse_bool(yaml_cfg.get('enabled', False))

    return _encryption_enabled


def get_chunk_size(yaml_cfg: Optional[Dict] = None) -> int:
    """Return the configured chunk size in bytes."""
    global _chunk_size
    if _chunk_size is not None:
        return _chunk_size

    if yaml_cfg is None:
        yaml_cfg = _load_yaml_config()

    env_val = os.environ.get(ENV_CHUNK_SIZE)
    if env_val is not None:
        try:
            _chunk_size = int(env_val)
        except ValueError:
            _chunk_size = DEFAULT_CHUNK_SIZE
    else:
        _chunk_size = int(yaml_cfg.get('chunk_size_bytes', DEFAULT_CHUNK_SIZE))

    # Clamp to valid range
    _chunk_size = max(MIN_CHUNK_SIZE, min(_chunk_size, MAX_CHUNK_SIZE))
    return _chunk_size


def get_allow_plaintext_fallback(yaml_cfg: Optional[Dict] = None) -> bool:
    """Return whether plaintext writes are allowed when encryption is disabled."""
    global _allow_plaintext_fallback
    if _allow_plaintext_fallback is not None:
        return _allow_plaintext_fallback

    if yaml_cfg is None:
        yaml_cfg = _load_yaml_config()

    env_val = os.environ.get(ENV_ALLOW_PLAINTEXT_FALLBACK)
    if env_val is not None:
        _allow_plaintext_fallback = _parse_bool(env_val)
    else:
        _allow_plaintext_fallback = _parse_bool(
            yaml_cfg.get('allow_plaintext_fallback', True)
        )

    return _allow_plaintext_fallback


def get_key_provider(yaml_cfg: Optional[Dict] = None, force: bool = False) -> Optional[KeyProvider]:
    """Return the configured KeyProvider singleton (lazy initialised).

    Args:
        yaml_cfg: Pre-loaded YAML encryption config dict (optional).
        force: If ``True``, attempt to load keys even when the global
            ``encryption.enabled`` flag is ``False``.  This is used by
            the storage worker to support per-device encryption — the
            device's ``encrypt_backups`` flag controls whether encryption
            is actually applied, not the global switch.

    Returns:
        ``None`` if no valid key material is available (or encryption is
        disabled and *force* is ``False``).

    Raises:
        KeyProviderError: If encryption is enabled (or *force* is set)
            and keys are configured but invalid (fail closed).
    """
    global _key_provider

    if _key_provider is not None:
        return _key_provider

    if yaml_cfg is None:
        yaml_cfg = _load_yaml_config()

    if not force and not get_encryption_enabled(yaml_cfg):
        logger.info('Encryption is disabled — no key provider initialised')
        return None

    provider_type = os.environ.get(ENV_KEY_PROVIDER, yaml_cfg.get('key_provider', PROVIDER_LOCAL))

    if provider_type == PROVIDER_LOCAL:
        keys = yaml_cfg.get('keys', {})
        default_kid = yaml_cfg.get('default_key_id')

        # Allow single key from env var
        env_key = os.environ.get(ENV_LOCAL_MASTER_KEY, '')
        if env_key and not keys:
            keys = {'local-env': env_key}
            default_kid = default_kid or 'local-env'

        if not keys:
            if force:
                # No keys configured — per-device encryption won't be available
                logger.info('No master keys configured — per-device encryption unavailable')
                return None
            # Fail closed: encryption enabled but no key
            raise KeyProviderError('Encryption is enabled but no master keys are configured')

        try:
            _key_provider = LocalKeyProvider(keys=keys, default_kid=default_kid)
        except KeyProviderError:
            if force:
                # Keys configured but invalid — log and return None
                logger.warning('Master keys configured but invalid — per-device encryption unavailable')
                return None
            raise
    else:
        raise KeyProviderError(
            f'Unsupported key provider: "{provider_type}". '
            'Supported providers: local. '
            'KMS providers will be available in a future release.'
        )

    return _key_provider


def reset_singletons() -> None:
    """Reset cached singletons (for testing)."""
    global _key_provider, _encryption_enabled, _chunk_size, _allow_plaintext_fallback
    _key_provider = None
    _encryption_enabled = None
    _chunk_size = None
    _allow_plaintext_fallback = None
