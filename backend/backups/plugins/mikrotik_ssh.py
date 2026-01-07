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

import paramiko

from .base import BackupPlugin


def _export_config(ip_address: str, credentials: Dict) -> str:
    username = credentials.get('username')
    password = credentials.get('password')
    if not username or not password:
        raise ValueError('Mikrotik SSH plugin requires username and password credentials')

    client = paramiko.SSHClient()
    client.set_missing_host_key_policy(paramiko.AutoAddPolicy())

    try:
        client.connect(
            hostname=ip_address,
            username=username,
            password=password,
            look_for_keys=False,
            allow_agent=False,
            timeout=10,
        )
        _, stdout, stderr = client.exec_command('/export show-sensitive')
        output = stdout.read().decode('utf-8', errors='ignore')
        error_text = stderr.read().decode('utf-8', errors='ignore')
        if error_text.strip():
            raise RuntimeError(f'Mikrotik export returned error: {error_text.strip()}')
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
