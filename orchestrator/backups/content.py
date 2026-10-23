"""Reading stored backups back through a storage worker."""

import hashlib
from functools import cache

from django.conf import settings
from django.core.exceptions import ImproperlyConfigured
from redis import Redis

from backups.jobs import storage_workers
from backups.models import BackupJob
from core import keys
from core.signing import sign_task
from devicevault.celery import app as celery_app
from devicevault_protocol.crypto import EncryptionHeader, decrypt_backup, is_encrypted
from devicevault_protocol.crypto.exceptions import CryptoError
from devicevault_protocol.names import READ_TASK, storage_queue_name


class ContentUnavailable(Exception):
    """The backup could not be read back."""


@cache
def _redis() -> Redis:
    return Redis.from_url(settings.DEVICEVAULT_BUS.redis_url)


def read_raw(job: BackupJob, *, timeout: int = 60) -> bytes:
    """The stored bytes of a successful job, exactly as written (possibly encrypted)."""
    if not job.succeeded or not job.storage_ref:
        raise ContentUnavailable('this backup was not stored')
    spec = {'backend': job.storage_backend, 'storage_ref': job.storage_ref}
    keys.add_secret(spec, 'config', job.location.config if job.location else {}, storage_workers(job.storage_backend))
    envelope = sign_task(spec)
    queue = storage_queue_name(job.storage_backend)
    try:
        result = celery_app.send_task(READ_TASK, args=[envelope], queue=queue).get(timeout=timeout)
    except Exception as exc:  # timeouts and broker errors alike
        raise ContentUnavailable(f'no storage worker answered for {queue}: {exc}') from exc
    if result.get('status') != 'success':
        raise ContentUnavailable(result.get('error') or 'the storage worker could not read the backup')

    redis = _redis()
    data = redis.get(result['key'])
    redis.delete(result['key'])
    if data is None:
        raise ContentUnavailable('the backup expired before it could be fetched')
    if hashlib.sha256(data).hexdigest() != job.stored_sha256:
        raise ContentUnavailable('the stored backup no longer matches its recorded hash')
    return data


def read_content(job: BackupJob) -> bytes:
    """The backup's plaintext content."""
    data = read_raw(job)
    if not job.encrypted:
        return data
    if not is_encrypted(data):
        raise ContentUnavailable('the backup should be encrypted but is not')
    try:
        header = EncryptionHeader.from_bytes(data)
        if header.aad.get('job_id') != str(job.id):
            raise ContentUnavailable('the encrypted backup belongs to a different job')
        return decrypt_backup(data, keys.vault())
    except (CryptoError, ImproperlyConfigured) as exc:
        raise ContentUnavailable(f'the backup could not be decrypted: {exc}') from exc
