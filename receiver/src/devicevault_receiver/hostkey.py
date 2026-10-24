"""The receiver's SSH host key, generated on first start and kept in the state volume.

Like ``identity.json`` this is self-generated state: deleting it gives the
receiver a new host key, which devices that pinned the old one will refuse.
"""

import os
from pathlib import Path

import asyncssh

from devicevault_protocol.identity import state_dir

HOST_KEY_FILENAME = 'ssh_host_ed25519_key'


def load_or_create(path: Path | None = None) -> asyncssh.SSHKey:
    path = path or state_dir() / HOST_KEY_FILENAME
    if path.exists():
        return asyncssh.read_private_key(path)
    key = asyncssh.generate_private_key('ssh-ed25519')
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(path.name + '.tmp')
    fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, 'wb') as handle:
        handle.write(key.export_private_key())
    os.replace(tmp, path)
    return key


def fingerprint(key: asyncssh.SSHKey) -> str:
    """OpenSSH style (``SHA256:...``), as ``ssh-keygen -lf`` and devices show it."""
    return key.get_fingerprint('sha256')
