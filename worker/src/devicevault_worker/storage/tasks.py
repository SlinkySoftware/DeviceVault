"""Storage tasks, all on a storage target's queue.

- ``job.store``: write a staged backup.
- ``storage.read``: read one back into Redis for the orchestrator.
- ``storage.check``: verify a target's settings work.
- ``storage.delete``: delete stored backups (retention).

Every task carries ``target`` (``{"id", "driver"}``) and the target's
settings as ``config`` or, with payload encryption, ``config_sealed``.
"""

import tempfile
import time
import uuid
from typing import Any

from celery.exceptions import SoftTimeLimitExceeded
from pydantic import ValidationError

from devicevault_protocol import blobs
from devicevault_protocol.jobs import (
    EVENT_DELETE_FAILED,
    EVENT_DELETED,
    EVENT_FAILED,
    EVENT_RETRYING,
    EVENT_STARTED,
    EVENT_STORED,
    READ_BLOB_TTL_SECONDS,
    STAGE_STORE,
    read_blob_key,
)
from devicevault_protocol.names import CHECK_TASK, DELETE_TASK, READ_TASK, STORE_TASK
from devicevault_protocol.trust import SignatureError, verified_payload
from devicevault_worker import events
from devicevault_worker.app import app, get_logger, redis_client
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

logger = get_logger('devicevault.worker.storage')

MAX_RETRIES = 5
# Pushed backups can be hundreds of MB.
STORE_TIME_LIMIT = 1800
READ_TIME_LIMIT = 600
DELETE_TIME_LIMIT = 600


def spool():
    """A temporary file for a backup in transit: in memory while small, on disk beyond one blob chunk."""
    return tempfile.SpooledTemporaryFile(max_size=blobs.CHUNK_SIZE)


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
    soft_time_limit=STORE_TIME_LIMIT,
    time_limit=STORE_TIME_LIMIT + 60,
)
def store(self, envelope: dict, blob: dict) -> None:
    """Write the backup staged at ``blob["key"]``.

    ``envelope`` (orchestrator-signed) carries job_id, target, config and
    name; ``blob`` comes from the collector or receiver and is checked
    against the hash it reported, both here and by the orchestrator.
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
        with spool() as data:
            staged = blobs.fetch(redis_client, blob['key'], data)
            if staged is None:
                raise StorageError('the collected backup expired before it could be stored')
            if staged['sha256'] != blob['sha256']:
                raise StorageError('the staged backup does not match the collected hash')
            data.seek(0)

            started = time.monotonic()
            try:
                ref = driver.store(data, BackupName(**spec['name']), params)
            except OSError as exc:  # disk full, NFS hiccup, git lock...
                raise StorageUnavailable(str(exc)) from exc
        blobs.delete(redis_client, blob['key'])
        log.info(f'stored {staged["size"]} bytes as {driver.key}:{ref}')
        events.send(
            job_id,
            EVENT_STORED,
            attempt=attempt,
            storage_ref=ref,
            sha256=blob['sha256'],
            size=staged['size'],
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


@app.task(name=READ_TASK, soft_time_limit=READ_TIME_LIMIT, time_limit=READ_TIME_LIMIT + 30)
def read(envelope: dict) -> dict:
    """Stage a stored backup in Redis: ``{"status": "success", "key", "sha256", "size"}``.

    The bytes go through Redis rather than the result, because backups can be
    hundreds of MB.
    """

    def work(spec):
        driver, params = open_target(spec)
        with spool() as data:
            driver.read(spec['storage_ref'], params, data)
            data.seek(0)
            return blobs.put(redis_client, read_blob_key(uuid.uuid4().hex), data, READ_BLOB_TTL_SECONDS)

    return _answer(READ_TASK, envelope, work)


@app.task(name=CHECK_TASK, soft_time_limit=60, time_limit=90)
def check(envelope: dict) -> dict:
    """``{"status": "success", "message", "worker_id"}`` if the target's settings work on this worker."""
    from devicevault_worker.app import identity

    def work(spec):
        driver, params = open_target(spec)
        return {'message': driver.check(params), 'worker_id': identity.worker_id}

    return _answer(CHECK_TASK, envelope, work)


@app.task(name=DELETE_TASK, soft_time_limit=DELETE_TIME_LIMIT, time_limit=DELETE_TIME_LIMIT + 30)
def delete(envelope: dict) -> None:
    """Delete the backups in ``items`` (``[{"job_id", "storage_ref"}]``), reporting each one.

    Not retried: an item that fails stays expired, and the orchestrator asks again later.
    """
    try:
        spec = verified_payload(envelope)
    except SignatureError as exc:
        logger.error('task_rejected', extra={'task': DELETE_TASK, 'reason': str(exc)})
        return

    items = spec.get('items') or []
    try:
        driver, params = open_target(spec)
    except StorageError as exc:
        for item in items:
            events.send(item['job_id'], EVENT_DELETE_FAILED, error=str(exc))
        return
    for item in items:
        log = CollectionLog(source='storage')
        try:
            driver.delete(item['storage_ref'], params)
        except SoftTimeLimitExceeded:
            return  # the rest stay unreported; the orchestrator asks again later
        except Exception as exc:
            if not isinstance(exc, StorageError | OSError):
                logger.exception('delete_failed', extra={'job_id': item['job_id']})
            events.send(item['job_id'], EVENT_DELETE_FAILED, error=str(exc) or exc.__class__.__name__)
        else:
            log.info(f'deleted {driver.key}:{item["storage_ref"]} (retention)')
            events.send(item['job_id'], EVENT_DELETED, log=log.entries)
