"""Backup method plugin loader.

Plugins are simple Python modules under ``backups.plugins`` that expose a
``PLUGIN`` variable containing a :class:`BackupPlugin` instance. The
scheduler imports and executes the plugin based on the device's configured
backup_method key.
"""

from importlib import import_module
import logging
import pkgutil
from typing import Dict, List, Optional

from .base import BackupPlugin

logger = logging.getLogger(__name__)

_plugin_cache: Optional[Dict[str, BackupPlugin]] = None


def _discover_plugins() -> Dict[str, BackupPlugin]:
    global _plugin_cache
    if _plugin_cache is not None:
        return _plugin_cache

    discovered: Dict[str, BackupPlugin] = {}
    for module_info in pkgutil.iter_modules(__path__):
        if module_info.name.startswith('_'):
            continue
        module_fqn = f"{__name__}.{module_info.name}"
        try:
            module = import_module(module_fqn)
        except Exception as exc:  # pragma: no cover - best effort discovery
            logger.error("Failed to import backup plugin %s: %s", module_fqn, exc)
            continue

        plugin = getattr(module, 'PLUGIN', None)
        if isinstance(plugin, BackupPlugin):
            discovered[plugin.key] = plugin
        else:
            logger.warning("Module %s missing PLUGIN definition; skipping", module_fqn)
    _plugin_cache = discovered
    return discovered


def list_plugins() -> List[BackupPlugin]:
    """Return all available plugins (cached)."""
    return list(_discover_plugins().values())


def get_plugin(key: str) -> Optional[BackupPlugin]:
    """Return a plugin by key if it exists."""
    return _discover_plugins().get(key)
