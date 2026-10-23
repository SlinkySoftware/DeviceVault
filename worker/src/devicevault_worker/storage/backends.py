"""Storage backends. Content is opaque bytes (it may be ciphertext).

A backend stores one backup of a device and returns a ``storage_ref`` from
which ``read`` returns exactly those bytes.

- ``fs``: one file per backup under ``config["path"]``, optionally gzipped
  (``config["compress"]``).
- ``git``: one file per device in a repository at ``config["path"]``, one
  commit per backup, so the history is the device's configuration history.
"""

import gzip
import os
import threading
from dataclasses import dataclass
from pathlib import Path

from git import Actor, Repo

_GZ_SUFFIX = '.gz'
_AUTHOR = Actor('DeviceVault', 'devicevault@localhost')


class StorageError(Exception):
    """The backend could not store or read a backup."""


@dataclass(frozen=True)
class BackupName:
    """How the orchestrator identifies a backup to a backend."""

    device_key: str  # stable per device, e.g. "42-core-router-01"
    job_id: str
    timestamp: str  # compact UTC, e.g. "20261023T041500Z"
    extension: str  # ".cfg" or ".bin"


def _base(config: dict, name: str) -> Path:
    base = config.get('path')
    if not base:
        raise StorageError(f'{name} storage requires "path" in the location config')
    return Path(base).resolve()


def _inside(base: Path, relative: str) -> Path:
    """Resolve ``relative`` under ``base``, refusing anything that escapes it."""
    path = (base / relative).resolve()
    if path != base and base not in path.parents:
        raise StorageError(f'storage path escapes the base directory: {relative}')
    return path


class FilesystemBackend:
    key = 'fs'

    def store(self, data: bytes, name: BackupName, config: dict) -> str:
        base = _base(config, 'filesystem')
        ref = f'{name.device_key}/{name.timestamp}-{name.job_id}{name.extension}'
        compress = bool(config.get('compress'))
        if compress:
            ref += _GZ_SUFFIX
        path = _inside(base, ref)
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp = path.with_name(path.name + '.part')
        with gzip.open(tmp, 'wb') if compress else open(tmp, 'wb') as handle:
            handle.write(data)
        os.replace(tmp, path)
        return ref

    def read(self, ref: str, config: dict) -> bytes:
        path = _inside(_base(config, 'filesystem'), ref)
        if not path.is_file():
            raise StorageError(f'backup not found: {ref}')
        opener = gzip.open if ref.endswith(_GZ_SUFFIX) else open
        with opener(path, 'rb') as handle:
            return handle.read()


class GitBackend:
    key = 'git'
    _lock = threading.Lock()  # one commit at a time per process

    def _repo(self, base: Path, branch: str) -> Repo:
        if not (base / '.git').exists():
            base.mkdir(parents=True, exist_ok=True)
            repo = Repo.init(base, initial_branch=branch)
        else:
            repo = Repo(base)
        if repo.head.is_valid() and repo.active_branch.name != branch:
            if branch in repo.heads:
                repo.heads[branch].checkout()
            else:
                repo.create_head(branch).checkout()
        return repo

    def store(self, data: bytes, name: BackupName, config: dict) -> str:
        base = _base(config, 'git')
        branch = config.get('branch', 'main')
        relative = f'{name.device_key}{name.extension}'
        path = _inside(base, relative)
        with self._lock:
            repo = self._repo(base, branch)
            path.write_bytes(data)
            repo.index.add([relative])
            message = f'{name.device_key}: backup {name.timestamp} (job {name.job_id})'
            commit = repo.index.commit(message, author=_AUTHOR, committer=_AUTHOR)
        return f'{branch}:{relative}@{commit.hexsha}'

    def read(self, ref: str, config: dict) -> bytes:
        base = _base(config, 'git')
        try:
            location, sha = ref.rsplit('@', 1)
            _branch, relative = location.split(':', 1)
        except ValueError as exc:
            raise StorageError(f'invalid git storage ref: {ref}') from exc
        _inside(base, relative)
        try:
            blob = Repo(base).commit(sha).tree / relative
            return blob.data_stream.read()
        except (ValueError, KeyError) as exc:
            raise StorageError(f'backup not found in git: {ref}') from exc


BACKENDS = {backend.key: backend for backend in (FilesystemBackend(), GitBackend())}
