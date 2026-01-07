"""Mikrotik RouterOS backup via SSH ``/export show-sensitive``."""

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
