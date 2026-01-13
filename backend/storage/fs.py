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
import base64
from typing import Dict, Union


def store_backup(content: Union[str, bytes], rel_path: str, config: Dict, is_binary: bool = False) -> str:
    """Persist backup content onto a filesystem path.

    Args:
        content: Raw device configuration (str for text, bytes or base64 str for binary).
        rel_path: Relative path under the configured base directory.
        config: Storage configuration containing ``base_path`` or ``path``.
        is_binary: True if content is binary, False if text (default).

    Returns:
        storage_ref: Relative path used to retrieve this backup later.
    
    For binary content:
        - If content is a base64-encoded string, it will be decoded to bytes before writing.
        - If content is already bytes, it will be written as-is.
    
    For text content:
        - Content is written as UTF-8 text.
    """
    base_path = config.get('base_path') or config.get('path')
    if not base_path:
        raise ValueError('filesystem storage requires base_path or path')

    os.makedirs(base_path, exist_ok=True)
    full_path = os.path.join(base_path, rel_path)
    os.makedirs(os.path.dirname(full_path), exist_ok=True)

    if is_binary:
        # Binary write mode
        if isinstance(content, str):
            # Assume base64-encoded string, decode to bytes
            try:
                binary_data = base64.b64decode(content)
            except Exception:
                # If decode fails, encode the string as latin-1 (preserves all bytes)
                binary_data = content.encode('latin-1')
        else:
            # Already bytes
            binary_data = content
        
        with open(full_path, 'wb') as handle:
            handle.write(binary_data)
    else:
        # Text write mode (existing behavior)
        with open(full_path, 'w', encoding='utf-8') as handle:
            handle.write(content or '')

    return rel_path


def read_backup(storage_ref: str, config: Dict, is_binary: bool = False) -> Union[str, bytes]:
    """Read a stored backup from the filesystem storage backend.
    
    Args:
        storage_ref: Relative path identifier of backup.
        config: Storage configuration containing ``base_path`` or ``path``.
        is_binary: True if backup is binary, False if text (default).
    
    Returns:
        str (text backup, UTF-8 decoded) or bytes (binary backup).
    """
    base_path = config.get('base_path') or config.get('path')
    if not base_path:
        raise ValueError('filesystem storage requires base_path or path')

    full_path = os.path.join(base_path, storage_ref)
    if not os.path.exists(full_path):
        raise FileNotFoundError(f'backup not found at {full_path}')

    if is_binary:
        # Binary read: return raw bytes
        with open(full_path, 'rb') as handle:
            return handle.read()
    else:
        # Text read: return decoded string
        with open(full_path, 'r', encoding='utf-8') as handle:
            return handle.read()
