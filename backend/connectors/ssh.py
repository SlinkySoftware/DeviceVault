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

import paramiko

class SSHConnector:
    def __init__(self, command='show running-config'):
        self.command = command
    def fetch_config(self, device, credential):
        client = paramiko.SSHClient(); client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
        client.connect(hostname=device.ip_address, username=credential.data.get('username'), password=credential.data.get('password'), look_for_keys=False)
        _, stdout, _ = client.exec_command(self.command)
        text = stdout.read().decode('utf-8', errors='ignore'); client.close(); return text
