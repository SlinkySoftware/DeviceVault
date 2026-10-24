"""Drivers that write to the worker's storage volume (``/srv/devicevault``).

Paths in their settings are relative to the volume, so a target can never
make a worker write elsewhere.
"""

import gzip
import os
import shutil
import threading
from pathlib import Path

from git import Actor, Repo
from git.exc import GitError
from pydantic import Field, field_validator

from .base import StorageDriver, StorageError, StorageParams

# The storage volume in the worker image. Not configurable; tests patch it.
VOLUME = Path('/srv/devicevault')
_GZ_SUFFIX = '.gz'
_AUTHOR = Actor('DeviceVault', 'devicevault@localhost')


class LocalParams(StorageParams):
    path: str = Field(
        description='Directory on the worker\'s storage volume, relative to /srv/devicevault (e.g. "backups/site-a")',
        min_length=1,
    )

    @field_validator('path')
    @classmethod
    def _relative(cls, value: str) -> str:
        value = value.strip().strip('/')
        if not value or '..' in Path(value).parts:
            raise ValueError('must be a directory inside the storage volume')
        return value


def _inside(base: Path, relative: str) -> Path:
    """Resolve ``relative`` under ``base``, refusing anything that escapes it."""
    path = (base / relative).resolve()
    if path != base and base not in path.parents:
        raise StorageError(f'storage path escapes the target directory: {relative}')
    return path


def _base(params: LocalParams) -> Path:
    return _inside(VOLUME.resolve(), params.path)


class FilesystemParams(LocalParams):
    compress: bool = Field(False, description='Gzip each backup')


class FilesystemDriver(StorageDriver):
    key = 'filesystem'
    name = 'Filesystem'
    description = "One file per backup in a directory on the worker's storage volume."
    Params = FilesystemParams

    def store(self, data, name, params):
        ref = self.object_name(name) + (_GZ_SUFFIX if params.compress else '')
        path = _inside(_base(params), ref)
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp = path.with_name(path.name + '.part')
        with gzip.open(tmp, 'wb') if params.compress else open(tmp, 'wb') as handle:
            shutil.copyfileobj(data, handle)
        os.replace(tmp, path)
        return ref

    def read(self, ref, params, sink):
        path = _inside(_base(params), ref)
        if not path.is_file():
            raise StorageError(f'backup not found: {ref}')
        with gzip.open(path, 'rb') if ref.endswith(_GZ_SUFFIX) else open(path, 'rb') as handle:
            shutil.copyfileobj(handle, sink)

    def delete(self, ref, params):
        _inside(_base(params), ref).unlink(missing_ok=True)

    def check(self, params):
        base = _base(params)
        base.mkdir(parents=True, exist_ok=True)
        probe = base / '.devicevault-check'
        probe.write_bytes(b'ok')
        probe.unlink()
        return f'{base} is writable'


class GitParams(LocalParams):
    branch: str = Field('main', min_length=1, description='Branch to commit backups to')


class GitDriver(StorageDriver):
    key = 'git'
    name = 'Git repository'
    description = 'One file per device in a git repository, one commit per backup: the history is the changelog.'
    Params = GitParams
    _lock = threading.Lock()  # one commit at a time per process

    def _repo(self, params: GitParams) -> Repo:
        base = _base(params)
        if not (base / '.git').exists():
            base.mkdir(parents=True, exist_ok=True)
            return Repo.init(base, initial_branch=params.branch)
        repo = Repo(base)
        if repo.head.is_valid() and repo.active_branch.name != params.branch:
            head = repo.heads[params.branch] if params.branch in repo.heads else repo.create_head(params.branch)
            head.checkout()
        return repo

    def store(self, data, name, params):
        relative = f'{name.device_key}{name.extension}'
        with self._lock:
            repo = self._repo(params)
            with open(_inside(_base(params), relative), 'wb') as handle:
                shutil.copyfileobj(data, handle)
            repo.index.add([relative])
            message = f'{name.device_key}: backup {name.timestamp} (job {name.job_id})'
            commit = repo.index.commit(message, author=_AUTHOR, committer=_AUTHOR)
        return f'{params.branch}:{relative}@{commit.hexsha}'

    def read(self, ref, params, sink):
        try:
            location, sha = ref.rsplit('@', 1)
            _branch, relative = location.split(':', 1)
        except ValueError as exc:
            raise StorageError(f'invalid git storage ref: {ref}') from exc
        _inside(_base(params), relative)
        try:
            with Repo(_base(params)) as repo:
                shutil.copyfileobj((repo.commit(sha).tree / relative).data_stream, sink)
        except (ValueError, KeyError, GitError) as exc:
            raise StorageError(f'backup not found in git: {ref}') from exc

    def delete(self, ref, params):
        # History is the point of this driver; retention prunes by rewriting it (later).
        raise StorageError('git targets keep every backup in their history')

    def check(self, params):
        with self._lock:
            repo = self._repo(params)
        return f'{repo.working_dir} ({params.branch})'
