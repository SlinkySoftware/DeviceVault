"""
No-op backup plugin for seeded/demo devices.

Copyright (C) 2026, Slinky Software

This program is free software: you can redistribute it and/or modify
it under the terms of the GNU General Public License as published by
the Free Software Foundation, either version 3 of the License, or
(at your option) any later version.

This program is distributed in the hope that it will be useful,
but WITHOUT ANY WARRANTY; without even the implied warranty of
MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
GNU General Public License for more details.

You should have received a copy of the GNU General Public License
along with this program.  If not, see <http://www.gnu.org/licenses/>.
"""

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
