"""Storage tasks: ``job.store`` writes a staged backup, ``storage.read`` reads one back."""

import time
import uuid

from celery.exceptions import SoftTimeLimitExceeded

from devicevault_protocol.jobs import (
    EVENT_FAILED,
    EVENT_RETRYING,
    EVENT_STARTED,
    EVENT_STORED,
    READ_BLOB_TTL_SECONDS,
    STAGE_STORE,
    read_blob_key,
)
from devicevault_protocol.names import READ_TASK, STORE_TASK
from devicevault_worker import blobs, events
from devicevault_worker.app import app, get_logger
from devicevault_worker.drivers.base import CollectionLog
from devicevault_worker.storage.backends import BACKENDS, BackupName, StorageError
from devicevault_worker.trust import SignatureError, verified_payload

logger = get_logger('devicevault.worker.storage')

STORAGE_BACKENDS = frozenset(BACKENDS)
MAX_RETRIES = 5


class _Retryable(Exception):
    pass


@app.task(
    bind=True,
    name=STORE_TASK,
    acks_late=True,
    reject_on_worker_lost=True,
    max_retries=MAX_RETRIES,
    soft_time_limit=300,
    time_limit=360,
)
def store(self, envelope: dict, blob: dict) -> None:
    """Write the backup staged at ``blob["key"]``.

    ``envelope`` (orchestrator-signed) carries job_id, backend, config and
    name; ``blob`` comes from the collector and is checked against the hash
    the collector reported, both here and by the orchestrator.
    """
    try:
        spec = verified_payload(envelope)
    except SignatureError as exc:
        logger.error('task_rejected', extra={'task': STORE_TASK, 'reason': str(exc)})
        return

    job_id = spec['job_id']
    attempt = self.request.retries + 1
    log = CollectionLog(source='storage')
    try:
        events.send(job_id, EVENT_STARTED, attempt=attempt, stage=STAGE_STORE)
        backend = BACKENDS.get(spec['backend'])
        if backend is None:
            raise StorageError(f'this storage worker has no "{spec["backend"]}" backend')
        data = blobs.get(blob['key'])
        if data is None:
            raise StorageError('the collected backup expired before it could be stored')
        if blobs.sha256(data) != blob['sha256']:
            raise StorageError('the staged backup does not match the collected hash')

        started = time.monotonic()
        try:
            ref = backend.store(data, BackupName(**spec['name']), spec.get('config') or {})
        except OSError as exc:  # disk full, NFS hiccup, git lock...
            raise _Retryable(str(exc)) from exc
        blobs.delete(blob['key'])
        log.info(f'stored {len(data)} bytes as {spec["backend"]}:{ref}')
        events.send(
            job_id,
            EVENT_STORED,
            attempt=attempt,
            storage_ref=ref,
            sha256=blob['sha256'],
            size=len(data),
            duration_ms=int((time.monotonic() - started) * 1000),
            log=log.entries,
        )
    except _Retryable as exc:
        if self.request.retries < self.max_retries:
            countdown = min(300, 10 * 2**self.request.retries)
            log.warning(f'attempt {attempt} failed, retrying in {countdown}s: {exc}')
            events.send(job_id, EVENT_RETRYING, attempt=attempt, stage=STAGE_STORE, error=str(exc), log=log.entries)
            raise self.retry(exc=exc, countdown=countdown) from exc
        _fail(job_id, attempt, f'{exc} (gave up after {attempt} attempts)', log)
    except SoftTimeLimitExceeded:
        _fail(job_id, attempt, 'storing exceeded its time limit', log)
    except Exception as exc:
        if not isinstance(exc, StorageError):
            logger.exception('store_failed', extra={'job_id': job_id})
        _fail(job_id, attempt, str(exc) or exc.__class__.__name__, log)


def _fail(job_id: str, attempt: int, error: str, log: CollectionLog) -> None:
    log.error(error)
    events.send(job_id, EVENT_FAILED, attempt=attempt, stage=STAGE_STORE, error=error, log=log.entries)


@app.task(bind=True, name=READ_TASK, soft_time_limit=120, time_limit=150)
def read(self, envelope: dict) -> dict:
    """Read a stored backup into Redis for the orchestrator.

    Returns ``{"status": "success", "key", "sha256", "size"}`` or
    ``{"status": "failure", "error"}``. The bytes are staged in Redis rather
    than returned, because backups can be tens of MB.
    """
    try:
        spec = verified_payload(envelope)
    except SignatureError as exc:
        logger.error('task_rejected', extra={'task': READ_TASK, 'reason': str(exc)})
        return {'status': 'failure', 'error': f'task rejected: {exc}'}
    try:
        backend = BACKENDS.get(spec['backend'])
        if backend is None:
            raise StorageError(f'this storage worker has no "{spec["backend"]}" backend')
        data = backend.read(spec['storage_ref'], spec.get('config') or {})
    except (StorageError, OSError) as exc:
        return {'status': 'failure', 'error': str(exc)}
    return {'status': 'success', **blobs.put(read_blob_key(uuid.uuid4().hex), data, READ_BLOB_TTL_SECONDS)}
