"""Backup bytes staged in Redis between processes.

Redis caps one value at 512 MB and backups can come close to it, so a blob is
stored as chunks (``<key>:0``, ``<key>:1``...) of at most ``CHUNK_SIZE``
bytes plus a manifest at ``<key>``: ``{"chunks", "size", "sha256"}``. The
manifest is written last, so a blob is either complete or absent. Both sides
stream, so no process holds a whole blob in memory unless it asks for bytes.

Messages refer to a blob as ``{"key", "sha256", "size"}`` (what ``put``
returns); readers check the hash they compute against the one in the message,
not the manifest.
"""

import hashlib
import io
import json
from typing import BinaryIO

from redis import Redis

CHUNK_SIZE = 32 * 1024 * 1024


def sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _chunk_key(key: str, index: int) -> str:
    return f'{key}:{index}'


def put(redis: Redis, key: str, source: bytes | BinaryIO, ttl_seconds: int, *, chunk_size: int = CHUNK_SIZE) -> dict:
    """Stage ``source`` (bytes, or a binary file read from its current position) under ``key``."""
    stream = io.BytesIO(source) if isinstance(source, bytes | bytearray) else source
    digest = hashlib.sha256()
    size = 0
    count = 0
    while True:
        chunk = stream.read(chunk_size)
        if not chunk and count:
            break
        redis.set(_chunk_key(key, count), chunk, ex=ttl_seconds)
        digest.update(chunk)
        size += len(chunk)
        count += 1
        if not chunk:
            break  # an empty blob is one empty chunk
    manifest = {'chunks': count, 'size': size, 'sha256': digest.hexdigest()}
    redis.set(key, json.dumps(manifest), ex=ttl_seconds)
    return {'key': key, 'sha256': manifest['sha256'], 'size': size}


def _manifest(redis: Redis, key: str) -> dict | None:
    raw = redis.get(key)
    if raw is None:
        return None
    try:
        manifest = json.loads(raw)
        return manifest if isinstance(manifest, dict) and int(manifest['chunks']) > 0 else None
    except ValueError, KeyError, TypeError:
        return None


def fetch(redis: Redis, key: str, sink: BinaryIO) -> dict | None:
    """Write the blob to ``sink``; return ``{"sha256", "size"}`` of what was written.

    None if the blob is missing or incomplete (expired chunks); ``sink`` may
    then hold part of it.
    """
    manifest = _manifest(redis, key)
    if manifest is None:
        return None
    digest = hashlib.sha256()
    size = 0
    for index in range(int(manifest['chunks'])):
        chunk = redis.get(_chunk_key(key, index))
        if chunk is None:
            return None
        sink.write(chunk)
        digest.update(chunk)
        size += len(chunk)
    return {'sha256': digest.hexdigest(), 'size': size}


def get(redis: Redis, key: str) -> bytes | None:
    """The whole blob in memory, or None. For blobs known to be small, and tests."""
    buffer = io.BytesIO()
    return buffer.getvalue() if fetch(redis, key, buffer) is not None else None


def delete(redis: Redis, key: str) -> None:
    manifest = _manifest(redis, key)
    chunks = int(manifest['chunks']) if manifest else 0
    redis.delete(key, *(_chunk_key(key, index) for index in range(chunks)))
