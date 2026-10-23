"""Storage tasks, all on a storage target's queue.

- ``job.store``: write a staged backup.
- ``storage.read``: read one back into Redis for the orchestrator.
- ``storage.check``: verify a target's settings work.

Every task carries ``target`` (``{"id", "driver"}``) and the target's
settings as ``config`` or, with payload encryption, ``config_sealed``.
"""

import time
import uuid
from typing import Any

from celery.exceptions import SoftTimeLimitExceeded
from pydantic import ValidationError

from devicevault_protocol.jobs import (
    EVENT_FAILED,
    EVENT_RETRYING,
    EVENT_STARTED,
    EVENT_STORED,
    READ_BLOB_TTL_SECONDS,
    STAGE_STORE,
    read_blob_key,
)
from devicevault_protocol.names import CHECK_TASK, READ_TASK, STORE_TASK
from devicevault_worker import blobs, events
from devicevault_worker.app import app, get_logger
from devicevault_worker.drivers.base import CollectionLog, PermanentError
from devicevault_worker.payload import secret
from devicevault_worker.storage.drivers import (
    BackupName,
    StorageDriver,
    StorageError,
    StorageParams,
    StorageUnavailable,
    get_driver,
)
from devicevault_worker.trust import SignatureError, verified_payload

logger = get_logger('devicevault.worker.storage')

MAX_RETRIES = 5


def open_target(spec: dict[str, Any]) -> tuple[StorageDriver, StorageParams]:
    """The driver and validated settings for the task's target."""
    driver_key = (spec.get('target') or {}).get('driver', '')
    driver = get_driver(driver_key)
    if driver is None:
        raise StorageError(f'this storage worker has no "{driver_key}" storage driver')
    try:
        params = driver.Params.model_validate(secret(spec, 'config') or {})
    except ValidationError as exc:
        raise StorageError(f'invalid storage target settings: {exc}') from exc
    return driver(), params


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

    ``envelope`` (orchestrator-signed) carries job_id, target, config and
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
        driver, params = open_target(spec)
        data = blobs.get(blob['key'])
        if data is None:
            raise StorageError('the collected backup expired before it could be stored')
        if blobs.sha256(data) != blob['sha256']:
            raise StorageError('the staged backup does not match the collected hash')

        started = time.monotonic()
        try:
            ref = driver.store(data, BackupName(**spec['name']), params)
        except OSError as exc:  # disk full, NFS hiccup, git lock...
            raise StorageUnavailable(str(exc)) from exc
        blobs.delete(blob['key'])
        log.info(f'stored {len(data)} bytes as {driver.key}:{ref}')
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
    except StorageUnavailable as exc:
        if self.request.retries < self.max_retries:
            countdown = min(300, 10 * 2**self.request.retries)
            log.warning(f'attempt {attempt} failed, retrying in {countdown}s: {exc}')
            events.send(job_id, EVENT_RETRYING, attempt=attempt, stage=STAGE_STORE, error=str(exc), log=log.entries)
            raise self.retry(exc=exc, countdown=countdown) from exc
        _fail(job_id, attempt, f'{exc} (gave up after {attempt} attempts)', log)
    except SoftTimeLimitExceeded:
        _fail(job_id, attempt, 'storing exceeded its time limit', log)
    except Exception as exc:
        if not isinstance(exc, StorageError | PermanentError):
            logger.exception('store_failed', extra={'job_id': job_id})
        _fail(job_id, attempt, str(exc) or exc.__class__.__name__, log)


def _fail(job_id: str, attempt: int, error: str, log: CollectionLog) -> None:
    log.error(error)
    events.send(job_id, EVENT_FAILED, attempt=attempt, stage=STAGE_STORE, error=error, log=log.entries)


def _answer(task: str, envelope: dict, work) -> dict:
    """Run ``work(spec)`` for a request/response task, turning failures into ``{"status": "failure"}``."""
    try:
        spec = verified_payload(envelope)
    except SignatureError as exc:
        logger.error('task_rejected', extra={'task': task, 'reason': str(exc)})
        return {'status': 'failure', 'error': f'task rejected: {exc}'}
    try:
        return {'status': 'success', **work(spec)}
    except (StorageError, PermanentError, OSError) as exc:
        return {'status': 'failure', 'error': str(exc) or exc.__class__.__name__}


@app.task(name=READ_TASK, soft_time_limit=120, time_limit=150)
def read(envelope: dict) -> dict:
    """Stage a stored backup in Redis: ``{"status": "success", "key", "sha256", "size"}``.

    The bytes go through Redis rather than the result, because backups can be
    tens of MB.
    """

    def work(spec):
        driver, params = open_target(spec)
        data = driver.read(spec['storage_ref'], params)
        return blobs.put(read_blob_key(uuid.uuid4().hex), data, READ_BLOB_TTL_SECONDS)

    return _answer(READ_TASK, envelope, work)


@app.task(name=CHECK_TASK, soft_time_limit=60, time_limit=90)
def check(envelope: dict) -> dict:
    """``{"status": "success", "message", "worker_id"}`` if the target's settings work on this worker."""
    from devicevault_worker.app import identity

    def work(spec):
        driver, params = open_target(spec)
        return {'message': driver.check(params), 'worker_id': identity.worker_id}

    return _answer(CHECK_TASK, envelope, work)
