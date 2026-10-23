"""The ``job.collect`` task: collect a device's configuration and hand it to storage."""

import time
from typing import Any

from celery.exceptions import SoftTimeLimitExceeded

from devicevault_protocol.jobs import (
    BLOB_TTL_SECONDS,
    EVENT_COLLECTED,
    EVENT_FAILED,
    EVENT_RETRYING,
    EVENT_STARTED,
    STAGE_COLLECT,
    blob_key,
)
from devicevault_protocol.names import COLLECT_TASK, STORE_TASK, device_lock_key
from devicevault_worker import blobs, events
from devicevault_worker.app import app, get_logger, redis_client
from devicevault_worker.drivers import get_driver
from devicevault_worker.drivers.base import CollectionLog, PermanentError, Target, TransientError
from devicevault_worker.payload import prepare, secret
from devicevault_worker.trust import SignatureError, verified_payload

logger = get_logger('devicevault.worker.collect')

MAX_RETRIES = 3
SOFT_TIME_LIMIT = 600


class DeviceBusy(TransientError):
    """Another job is collecting this device right now."""


# Delete the lock only if this job still holds it.
_RELEASE = """
if redis.call('get', KEYS[1]) == ARGV[1] then
    return redis.call('del', KEYS[1])
end
return 0
"""


class DeviceLock:
    """One collection per device at a time, held in Redis under the job id.

    If a worker dies mid-collection, the broker redelivers the job; the
    redelivered copy reclaims its own lock instead of waiting for it to expire.
    """

    def __init__(self, redis, device_id: int, job_id: str, ttl: int):
        self.redis = redis
        self.key = device_lock_key(device_id)
        self.job_id = job_id
        self.ttl = ttl
        self.held = False

    def acquire(self) -> bool:
        if self.redis.set(self.key, self.job_id, nx=True, ex=self.ttl):
            self.held = True
        else:
            holder = self.redis.get(self.key)
            if holder is not None and holder.decode() == self.job_id:
                self.redis.expire(self.key, self.ttl)
                self.held = True
        return self.held

    def release(self) -> None:
        if self.held:
            self.redis.eval(_RELEASE, 1, self.key, self.job_id)
            self.held = False


def _backoff(retries: int) -> int:
    return min(300, 15 * 2**retries)


@app.task(
    bind=True,
    name=COLLECT_TASK,
    acks_late=True,
    reject_on_worker_lost=True,
    max_retries=MAX_RETRIES,
    soft_time_limit=SOFT_TIME_LIMIT,
    time_limit=SOFT_TIME_LIMIT + 60,
)
def collect(self, envelope: dict) -> None:
    try:
        job = verified_payload(envelope)
    except SignatureError as exc:
        # Unverifiable, so its job id cannot be trusted either: log and drop it.
        logger.error('task_rejected', extra={'task': COLLECT_TASK, 'reason': str(exc)})
        return

    job_id = job['job_id']
    attempt = self.request.retries + 1
    log = CollectionLog(source=job.get('driver', 'collector'))
    lock = DeviceLock(redis_client, job['device']['id'], job_id, ttl=SOFT_TIME_LIMIT + 120)

    try:
        if not lock.acquire():
            raise DeviceBusy('another backup job is collecting this device')
        events.send(job_id, EVENT_STARTED, attempt=attempt)
        started = time.monotonic()
        content, is_binary = _collect(job, log)
        data, encrypted = prepare(content, job)
        blob = blobs.put(blob_key(job_id), data, BLOB_TTL_SECONDS)
        # Report first: the orchestrator records the hash the store step must match.
        events.send(
            job_id,
            EVENT_COLLECTED,
            attempt=attempt,
            sha256=blob['sha256'],
            size=blob['size'],
            is_binary=is_binary,
            encrypted=encrypted,
            duration_ms=int((time.monotonic() - started) * 1000),
            log=log.entries,
        )
        store = job['store']
        app.send_task(STORE_TASK, args=[store['envelope'], blob], queue=store['queue'])
    except TransientError as exc:
        if self.request.retries < self.max_retries:
            countdown = _backoff(self.request.retries)
            log.warning(f'attempt {attempt} failed, retrying in {countdown}s: {exc}')
            events.send(job_id, EVENT_RETRYING, attempt=attempt, stage=STAGE_COLLECT, error=str(exc), log=log.entries)
            raise self.retry(exc=exc, countdown=countdown) from exc
        _fail(job_id, attempt, f'{exc} (gave up after {attempt} attempts)', log)
    except SoftTimeLimitExceeded:
        _fail(job_id, attempt, f'collection exceeded {SOFT_TIME_LIMIT}s', log)
    except Exception as exc:  # PermanentError and anything unexpected
        if not isinstance(exc, PermanentError):
            logger.exception('collect_failed', extra={'job_id': job_id})
        _fail(job_id, attempt, str(exc) or exc.__class__.__name__, log)
    finally:
        lock.release()


def _collect(job: dict[str, Any], log: CollectionLog) -> tuple[bytes, bool]:
    driver_cls = get_driver(job['driver'])
    if driver_cls is None:
        raise PermanentError(f'this collector has no "{job["driver"]}" driver')
    try:
        params = driver_cls.Params.model_validate(job.get('driver_params') or {})
    except ValueError as exc:
        raise PermanentError(f'invalid driver parameters: {exc}') from exc
    device = job['device']
    target = Target(address=device['address'], name=device.get('name', ''))
    credentials = secret(job, 'credentials') or {}
    content = driver_cls().collect(target, credentials, params, timeout=int(job.get('timeout', 120)), log=log)
    if isinstance(content, str):
        content = content.encode('utf-8')
    return content, driver_cls.is_binary


def _fail(job_id: str, attempt: int, error: str, log: CollectionLog) -> None:
    log.error(error)
    events.send(job_id, EVENT_FAILED, attempt=attempt, stage=STAGE_COLLECT, error=error, log=log.entries)
