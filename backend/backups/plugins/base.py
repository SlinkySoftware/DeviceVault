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
from typing import Callable, Dict, List, Optional
from datetime import datetime
from uuid import uuid4
import json

BackupCallable = Callable[[str, Dict], str]


class CollectorException(Exception):
    """Base exception for collector plugin failures."""
    pass


class CollectorTimeoutException(CollectorException):
    """Raised when collector operation times out."""
    pass


class CollectorAuthException(CollectorException):
    """Raised when authentication fails."""
    pass


class CollectorPluginException(CollectorException):
    """Raised when plugin execution fails."""
    pass


@dataclass
class BackupPlugin:
    """
    Metadata and entrypoint for a backup method plugin.
    
    Plugins now conform to a Celery-compatible collection contract:
    - Accept a JSON-serializable config dict
    - Support timeout parameter
    - Raise structured exceptions
    - Return JSON result with task metadata
    """
    key: str
    friendly_name: str
    description: str
    entrypoint: BackupCallable

    def run(self, ip_address: str, credentials: Dict) -> str:
        """
        Invoke the plugin entrypoint with normalized arguments (legacy sync mode).
        Returns raw device configuration as string.
        """
        return self.entrypoint(ip_address, credentials)

    def collect_async(self, config: Dict, timeout: int = 30, task_id: str = None) -> Dict:
        """
        Celery-compatible async collection interface.
        
        Args:
            config: JSON-serializable dict with keys:
                    - ip: Device IP address
                    - username: Authentication username
                    - password: Authentication password
                    - <plugin-specific>: Additional plugin-specific parameters
            timeout: Timeout in seconds (default 30)
            task_id: Celery task ID for tracking (auto-generated if not provided)
        
        Returns:
            Dict with schema:
            {
                "task_id": "<task_id or celery id>",
                "status": "success" | "failure",
                "timestamp": "<iso8601 utc>",
                "log": ["<action message>", ...],
                "device_config_ref": "<storage identifier or path or None>"
            }
        """
        if not task_id:
            task_id = str(uuid4())
        
        log_messages = []
        
        try:
            # Validate required parameters
            if "ip" not in config:
                raise CollectorException("Missing required parameter: ip")
            if "username" not in config:
                raise CollectorException("Missing required parameter: username")
            if "password" not in config:
                raise CollectorException("Missing required parameter: password")
            
            ip = config["ip"]
            username = config["username"]
            password = config["password"]
            
            log_messages.append(f"Starting collection for {ip} with plugin {self.key}")
            
            # Run the plugin with legacy interface
            credentials = {
                "username": username,
                "password": password,
            }
            # Pass through any additional config parameters for plugin-specific use
            for key, value in config.items():
                if key not in ("ip", "username", "password"):
                    credentials[key] = value
            
            device_config = self.entrypoint(ip, credentials)
            log_messages.append("Device configuration retrieved successfully")
            
            # Device config is stored externally; we only return a reference
            # The caller (Celery task) is responsible for storing and creating the ref
            return {
                "task_id": task_id,
                "status": "success",
                "timestamp": datetime.utcnow().isoformat() + "Z",
                "log": log_messages,
                "device_config_ref": None,  # Set by caller after external storage
                "_raw_device_config": device_config  # Internal; not returned to ORM
            }
        except CollectorTimeoutException as e:
            log_messages.append(f"Timeout: {str(e)}")
            return {
                "task_id": task_id,
                "status": "failure",
                "timestamp": datetime.utcnow().isoformat() + "Z",
                "log": log_messages,
                "device_config_ref": None
            }
        except CollectorAuthException as e:
            log_messages.append(f"Authentication failed: {str(e)}")
            return {
                "task_id": task_id,
                "status": "failure",
                "timestamp": datetime.utcnow().isoformat() + "Z",
                "log": log_messages,
                "device_config_ref": None
            }
        except CollectorException as e:
            log_messages.append(f"Collection error: {str(e)}")
            return {
                "task_id": task_id,
                "status": "failure",
                "timestamp": datetime.utcnow().isoformat() + "Z",
                "log": log_messages,
                "device_config_ref": None
            }
        except Exception as e:
            log_messages.append(f"Unexpected error: {str(e)}")
            return {
                "task_id": task_id,
                "status": "failure",
                "timestamp": datetime.utcnow().isoformat() + "Z",
                "log": log_messages,
                "device_config_ref": None
            }
