"""
Dummy binary backup plugin for testing/demo purposes.

This plugin generates a small binary blob to simulate firmware or binary configuration
backups. In production, replace the implementation with actual binary collection logic.

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

from typing import Dict, Any, Optional
from datetime import datetime
import base64

from .base import BackupPlugin


def _generate_binary_backup(config: Dict[str, Any], timeout: Optional[int] = None) -> Dict[str, Any]:
    """
    Generate a dummy binary backup.
    
    In production, this would:
    - Connect to device via SSH/TFTP/SCP
    - Download firmware or binary config
    - Return as base64-encoded string (for JSON serialization)
    
    Args:
        config: Configuration dict with 'ip' and 'credentials' keys.
        timeout: Optional timeout in seconds.
    
    Returns:
        Standard collector result dict with:
        - status: 'success' or 'failure'
        - device_config: base64-encoded binary string (for JSON transport)
        - log: List of log messages
        - timestamp: ISO8601 UTC timestamp
    """
    ip_address = config.get('ip') or config.get('ip_address')
    credentials = config.get('credentials') or {}

    try:
        # Validate inputs
        if not ip_address:
            return {
                'task_id': None,
                'status': 'failure',
                'timestamp': datetime.utcnow().isoformat() + 'Z',
                'log': ['missing ip_address in config'],
                'device_config': None
            }

        # In real plugin: connect to device and download binary
        # For demo: generate fake binary blob with magic header
        # Simulate 1MB firmware blob (in production, could be 250MB+)
        magic_header = b'\xFF\xFE' + b'FIRMWARE_HEADER_DEMO'
        fake_firmware = magic_header + (b'\x00' * (1024 * 1024 - len(magic_header)))

        # Encode to base64 for JSON transport
        # NOTE: This increases size by ~33%. For 250MB: ~333MB
        # Acceptable for operational simplicity over complex streaming
        encoded_binary = base64.b64encode(fake_firmware).decode('ascii')

        return {
            'task_id': None,
            'status': 'success',
            'timestamp': datetime.utcnow().isoformat() + 'Z',
            'log': [
                f'Connected to device at {ip_address}',
                f'Downloaded binary firmware: {len(fake_firmware)} bytes',
                f'Base64 encoded for transport: {len(encoded_binary)} bytes'
            ],
            'device_config': encoded_binary  # BASE64 STRING
        }

    except Exception as exc:
        return {
            'task_id': None,
            'status': 'failure',
            'timestamp': datetime.utcnow().isoformat() + 'Z',
            'log': [f'binary_backup_failed: {repr(exc)}'],
            'device_config': None
        }


PLUGIN = BackupPlugin(
    key='binary_dummy',
    friendly_name='Binary Dummy (Demo)',
    description='Demo binary backup plugin (1MB dummy firmware). For testing binary backup functionality. DO NOT use in production.',
    entrypoint=_generate_binary_backup,
    is_binary=True  # <-- CRITICAL: Mark as binary
)
