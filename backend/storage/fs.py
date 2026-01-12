"""
DeviceVault - A comprehensive network device backup management application with web interface for user and admin access and backend component for automated backup collection.
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

import os
from typing import Dict


def store_backup(content: str, rel_path: str, config: Dict) -> str:
    """Persist backup content onto a filesystem path.

    Args:
        content: Raw device configuration text.
        rel_path: Relative path under the configured base directory.
        config: Storage configuration containing ``base_path`` or ``path``.

    Returns:
        storage_ref: Relative path used to retrieve this backup later.
    """
    base_path = config.get('base_path') or config.get('path')
    if not base_path:
        raise ValueError('filesystem storage requires base_path or path')

    os.makedirs(base_path, exist_ok=True)
    full_path = os.path.join(base_path, rel_path)
    os.makedirs(os.path.dirname(full_path), exist_ok=True)

    with open(full_path, 'w', encoding='utf-8') as handle:
        handle.write(content or '')

    return rel_path


def read_backup(storage_ref: str, config: Dict) -> str:
    """Read a stored backup from the filesystem storage backend."""
    base_path = config.get('base_path') or config.get('path')
    if not base_path:
        raise ValueError('filesystem storage requires base_path or path')

    full_path = os.path.join(base_path, storage_ref)
    if not os.path.exists(full_path):
        raise FileNotFoundError(f'backup not found at {full_path}')

    with open(full_path, 'r', encoding='utf-8') as handle:
        return handle.read()
