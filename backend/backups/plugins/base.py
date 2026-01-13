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

from dataclasses import dataclass
from typing import Callable, Dict, List, Optional, Any
from datetime import datetime

# New plugin contract:
# - entrypoint accepts a configuration dict and an optional timeout (seconds)
# - entrypoint returns a JSON-serializable dict matching the collector result schema
#   (task_id will be filled by the Celery task wrapper when run inside a task)

# Collector entrypoint signature: Callable[[Dict, Optional[int]], Dict]
CollectorCallable = Callable[[Dict, Optional[int]], Dict]


@dataclass
class BackupPlugin:
    """Metadata and entrypoint for a backup method plugin.

    Plugins SHOULD accept a `config` dict containing at minimum:
      - ip: str
      - credentials: dict

    and an optional `timeout` (int seconds).

    The plugin entrypoint should return a dict with the following keys:
    {
      "task_id": None | str,
      "status": "success" | "failure",
      "timestamp": "<iso8601 utc>",
      "log": ["..."],
      "device_config": "<raw device config string or bytes representation>",
      "is_binary": bool (optional, defaults to False)
    }

    For binary backups, device_config must be base64-encoded string (JSON serializable).

    The Celery task wrapper will populate `task_id` and persist results.
    """
    key: str
    friendly_name: str
    description: str
    entrypoint: CollectorCallable
    is_binary: bool = False  # True for binary backups, False for text

    def run(self, config: Dict, timeout: Optional[int] = None) -> Dict[str, Any]:
        """Invoke the plugin entrypoint and normalize its result.

        This wrapper ensures a minimal, well-formed result dict is returned
        even if the plugin returns a raw string or raises an exception.
        """
        try:
            result = self.entrypoint(config, timeout)
        except Exception as exc:  # plugin raised; return structured failure
            return {
                'task_id': None,
                'status': 'failure',
                'timestamp': datetime.utcnow().isoformat() + 'Z',
                'log': [f'plugin_exception: {repr(exc)}'],
                'device_config': None
            }

        # Allow plugins to return a raw string (old contract) or dict (new contract)
        if isinstance(result, dict):
            # Ensure required keys
            return {
                'task_id': result.get('task_id'),
                'status': result.get('status', 'failure'),
                'timestamp': result.get('timestamp') or (datetime.utcnow().isoformat() + 'Z'),
                'log': result.get('log') or [],
                'device_config': result.get('device_config')
            }
        else:
            # Treat any non-dict as raw device config
            return {
                'task_id': None,
                'status': 'success',
                'timestamp': datetime.utcnow().isoformat() + 'Z',
                'log': ['plugin_returned_raw_string'],
                'device_config': result
            }
