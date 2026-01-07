"""No-op backup plugin for seeded/demo devices."""

from typing import Dict

from .base import BackupPlugin


def _noop_export(ip_address: str, credentials: Dict) -> str:
    return ''


PLUGIN = BackupPlugin(
    key='noop',
    friendly_name='No Operation',
    description='Skips backup execution and returns empty content (used for demo devices).',
    entrypoint=_noop_export,
)
