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

import os
import base64
from typing import Dict, Tuple, Union

from git import Repo


def _ensure_repo(repo_path: str, branch: str) -> Repo:
    """Return a Repo and ensure the requested branch exists."""
    if not os.path.exists(repo_path):
        os.makedirs(repo_path, exist_ok=True)
        repo = Repo.init(repo_path)
    else:
        repo = Repo.init(repo_path)

    try:
        repo.git.rev_parse('--verify', branch)
    except Exception:
        repo.git.checkout('-b', branch)
    else:
        repo.git.checkout(branch)

    return repo


def _parse_storage_ref(storage_ref: str) -> Tuple[str, str, str]:
    """Split storage_ref into branch, rel_path, commit components."""
    commit = None
    branch_rel = storage_ref
    if '@' in storage_ref:
        branch_rel, commit = storage_ref.split('@', 1)

    if ':' in branch_rel:
        branch, rel_path = branch_rel.split(':', 1)
    else:
        branch, rel_path = 'main', branch_rel

    return branch, rel_path, commit


def store_backup(content: Union[str, bytes], rel_path: str, config: Dict, is_binary: bool = False) -> str:
    """Persist backup content to a Git repository and return an opaque ref.
    
    Args:
        content: str (text) or bytes (binary, base64-decoded from plugin).
        rel_path: Relative path under Git repo.
        config: Storage configuration with repo_path, branch, etc.
        is_binary: True if content is binary, False if text.
    
    Returns:
        storage_ref: Opaque reference in format "branch:rel_path@commit_sha"
    """
    repo_path = config.get('repo_path') or config.get('path')
    if not repo_path:
        raise ValueError('git storage requires repo_path or path')

    branch = config.get('branch', 'main')
    repo = _ensure_repo(repo_path, branch)

    full_path = os.path.join(repo_path, rel_path)
    os.makedirs(os.path.dirname(full_path), exist_ok=True)
    
    if is_binary:
        # Binary write
        if isinstance(content, str):
            # Assume base64-encoded string, decode to bytes
            try:
                binary_data = base64.b64decode(content)
            except Exception:
                binary_data = content.encode('latin-1')
        else:
            binary_data = content
        
        with open(full_path, 'wb') as handle:
            handle.write(binary_data)
    else:
        # Text write
        with open(full_path, 'w', encoding='utf-8') as handle:
            handle.write(content or '')

    repo.index.add([full_path])
    message = config.get('commit_message', f'devicevault: save {rel_path}')
    commit = repo.index.commit(message)
    storage_ref = f"{branch}:{rel_path}@{commit.hexsha}"
    return storage_ref


def read_backup(storage_ref: str, config: Dict, is_binary: bool = False) -> Union[str, bytes]:
    """Read a stored backup from a Git repository.
    
    Args:
        storage_ref: Opaque reference in format "branch:rel_path@commit_sha".
        config: Storage configuration with repo_path.
        is_binary: True if backup is binary, False if text.
    
    Returns:
        str (text, UTF-8 decoded) or bytes (binary).
    """
    repo_path = config.get('repo_path') or config.get('path')
    if not repo_path:
        raise ValueError('git storage requires repo_path or path')

    branch, rel_path, commit = _parse_storage_ref(storage_ref)
    repo = Repo(repo_path)

    target = commit or branch
    blob_ref = f"{target}:{rel_path}"
    try:
        blob_bytes = repo.git.show(blob_ref, raw=True)
        if is_binary:
            # Return raw bytes
            if isinstance(blob_bytes, str):
                return blob_bytes.encode('latin-1')
            return blob_bytes
        else:
            # Decode to string
            if isinstance(blob_bytes, bytes):
                return blob_bytes.decode('utf-8')
            return blob_bytes
    except Exception:
        # Fallback to reading from working tree if blob lookup fails
        full_path = os.path.join(repo_path, rel_path)
        if not os.path.exists(full_path):
            raise
        
        if is_binary:
            with open(full_path, 'rb') as handle:
                return handle.read()
        else:
            with open(full_path, 'r', encoding='utf-8') as handle:
                return handle.read()
