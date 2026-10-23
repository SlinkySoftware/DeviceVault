"""Backup bytes staged in Redis between collection and storage."""

import hashlib

from devicevault_worker.app import redis_client


def sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def put(key: str, data: bytes, ttl_seconds: int) -> dict:
    redis_client.set(key, data, ex=ttl_seconds)
    return {'key': key, 'sha256': sha256(data), 'size': len(data)}


def get(key: str) -> bytes | None:
    return redis_client.get(key)


def delete(key: str) -> None:
    redis_client.delete(key)
