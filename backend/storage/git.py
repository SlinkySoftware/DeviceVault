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
import logging
from typing import Dict, Tuple, Union

from git import Repo

logger = logging.getLogger('devicevault.storage.git')


def _ensure_repo(repo_path: str, branch: str) -> Repo:
    """Return a Repo and ensure the requested branch exists."""
    if not os.path.exists(repo_path):
        logger.info(f'Initializing new Git repository at {repo_path}')
        os.makedirs(repo_path, exist_ok=True)
        repo = Repo.init(repo_path)
    else:
        repo = Repo.init(repo_path)

    try:
        repo.git.rev_parse('--verify', branch)
        logger.debug(f'Checking out existing branch: {branch}')
    except Exception:
        logger.info(f'Creating new branch: {branch}')
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
    logger.info(f'Storing backup to Git repository: {rel_path} on branch {branch} (binary={is_binary})')
    repo = _ensure_repo(repo_path, branch)

    full_path = os.path.join(repo_path, rel_path)
    os.makedirs(os.path.dirname(full_path), exist_ok=True)
    
    if is_binary:
        # Binary write
        if isinstance(content, str):
            # Assume base64-encoded string, decode to bytes
            try:
                binary_data = base64.b64decode(content)
                logger.debug(f'Decoded base64 content ({len(binary_data)} bytes)')
            except Exception:
                binary_data = content.encode('latin-1')
                logger.debug(f'Encoded string as latin-1 ({len(binary_data)} bytes)')
        else:
            binary_data = content
            logger.debug(f'Using raw binary content ({len(binary_data)} bytes)')
        
        with open(full_path, 'wb') as handle:
            handle.write(binary_data)
        logger.debug(f'Wrote {len(binary_data)} bytes to {full_path}')
    else:
        # Text write
        content_len = len(content or '')
        with open(full_path, 'w', encoding='utf-8') as handle:
            handle.write(content or '')
        logger.debug(f'Wrote {content_len} characters to {full_path}')

    repo.index.add([full_path])
    message = config.get('commit_message', f'devicevault: save {rel_path}')
    commit = repo.index.commit(message)
    logger.info(f'Committed to Git: {commit.hexsha[:8]} - "{message}"')
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
    logger.info(f'Reading backup from Git: {storage_ref} (binary={is_binary})')
    repo = Repo(repo_path)

    target = commit or branch
    blob_ref = f"{target}:{rel_path}"
    try:
        logger.debug(f'Retrieving Git blob: {blob_ref}')
        blob_bytes = repo.git.show(blob_ref, raw=True)
        if is_binary:
            # Return raw bytes
            if isinstance(blob_bytes, str):
                data = blob_bytes.encode('latin-1')
            else:
                data = blob_bytes
            logger.info(f'Read {len(data)} bytes from Git blob {blob_ref}')
            return data
        else:
            # Decode to string
            if isinstance(blob_bytes, bytes):
                data = blob_bytes.decode('utf-8')
            else:
                data = blob_bytes
            logger.info(f'Read {len(data)} characters from Git blob {blob_ref}')
            return data
    except Exception as e:
        logger.warning(f'Failed to read Git blob {blob_ref}, falling back to working tree: {e}')
        # Fallback to reading from working tree if blob lookup fails
        full_path = os.path.join(repo_path, rel_path)
        if not os.path.exists(full_path):
            logger.error(f'Backup not found in Git or working tree: {full_path}')
            raise
        
        if is_binary:
            with open(full_path, 'rb') as handle:
                data = handle.read()
            logger.info(f'Read {len(data)} bytes from working tree {full_path}')
            return data
        else:
            with open(full_path, 'r', encoding='utf-8') as handle:
                data = handle.read()
            logger.info(f'Read {len(data)} characters from working tree {full_path}')
            return data
