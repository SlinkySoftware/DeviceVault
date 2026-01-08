"""
Mikrotik RouterOS backup via SSH ``/export show-sensitive``.

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
import socket

import paramiko

from .base import BackupPlugin, CollectorAuthException, CollectorTimeoutException, CollectorPluginException


def _export_config(ip_address: str, credentials: Dict) -> str:
    """
    Execute /export show-sensitive on RouterOS via SSH.
    
    Raises:
        CollectorAuthException: If SSH authentication fails
        CollectorTimeoutException: If connection or command times out
        CollectorPluginException: If device command execution fails
    """
    username = credentials.get('username')
    password = credentials.get('password')
    timeout = credentials.get('timeout', 30)
    
    if not username or not password:
        raise CollectorAuthException('Mikrotik SSH plugin requires username and password credentials')

    client = paramiko.SSHClient()
    client.set_missing_host_key_policy(paramiko.AutoAddPolicy())

    try:
        try:
            client.connect(
                hostname=ip_address,
                username=username,
                password=password,
                look_for_keys=False,
                allow_agent=False,
                timeout=timeout,
            )
        except socket.timeout:
            raise CollectorTimeoutException(f'SSH connection to {ip_address} timed out after {timeout}s')
        except paramiko.AuthenticationException as e:
            raise CollectorAuthException(f'SSH authentication failed for {ip_address}: {str(e)}')
        except paramiko.SSHException as e:
            raise CollectorPluginException(f'SSH error: {str(e)}')
        except OSError as e:
            raise CollectorPluginException(f'Network error connecting to {ip_address}: {str(e)}')
        
        # Execute export command with timeout
        try:
            _, stdout, stderr = client.exec_command('/export show-sensitive', timeout=timeout)
            output = stdout.read().decode('utf-8', errors='ignore')
            error_text = stderr.read().decode('utf-8', errors='ignore')
        except socket.timeout:
            raise CollectorTimeoutException(f'Export command execution timed out after {timeout}s')
        
        if error_text.strip():
            raise CollectorPluginException(f'Mikrotik export returned error: {error_text.strip()}')
        
        return output
    finally:
        try:
            client.close()
        except Exception:
            pass


PLUGIN = BackupPlugin(
    key='mikrotik_ssh_export',
    friendly_name='Mikrotik SSH Export',
    description='Connects to RouterOS over SSH and runs /export show-sensitive to capture full configuration.',
    entrypoint=_export_config,
)
