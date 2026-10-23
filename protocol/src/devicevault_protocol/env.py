"""Environment configuration helpers shared by the orchestrator and workers.

Every setting is read from a ``DV_*`` environment variable. Any variable can
instead be supplied as a file by setting ``<NAME>_FILE`` to its path, which is
how Docker secrets are mounted. The file wins when both are set.
"""

import os
from pathlib import Path

_TRUE = {'1', 'true', 'yes', 'on'}
_FALSE = {'0', 'false', 'no', 'off', ''}


class ConfigError(ValueError):
    """Raised when an environment setting is missing or malformed."""


def env_str(name: str, default: str | None = None, *, required: bool = False) -> str | None:
    file_path = os.environ.get(f'{name}_FILE')
    if file_path:
        try:
            return Path(file_path).read_text(encoding='utf-8').strip()
        except OSError as exc:
            raise ConfigError(f'{name}_FILE points to an unreadable file: {file_path}') from exc

    value = os.environ.get(name)
    if value is None:
        if required:
            raise ConfigError(f'{name} must be set')
        return default
    return value


def env_bool(name: str, default: bool) -> bool:
    value = env_str(name)
    if value is None:
        return default
    normalised = value.strip().lower()
    if normalised in _TRUE:
        return True
    if normalised in _FALSE:
        return False
    raise ConfigError(f'{name} must be a boolean, got {value!r}')


def env_int(name: str, default: int, *, minimum: int | None = None) -> int:
    value = env_str(name)
    if value is None or not value.strip():
        return default
    try:
        parsed = int(value)
    except ValueError as exc:
        raise ConfigError(f'{name} must be an integer, got {value!r}') from exc
    if minimum is not None and parsed < minimum:
        raise ConfigError(f'{name} must be >= {minimum}, got {parsed}')
    return parsed


def env_list(name: str, default: list[str] | None = None) -> list[str]:
    value = env_str(name)
    if value is None:
        return list(default or [])
    return [item.strip() for item in value.split(',') if item.strip()]


def env_map(name: str) -> dict[str, str]:
    """Parse ``key=value,key2=value2`` into a dict."""
    result = {}
    for item in env_list(name):
        key, sep, value = item.partition('=')
        if not sep or not key.strip() or not value.strip():
            raise ConfigError(f'{name} entries must be key=value, got {item!r}')
        result[key.strip()] = value.strip()
    return result
