"""Creating, dispatching and tracking backup jobs. See devicevault_protocol.jobs."""

import logging
import re
import uuid
from datetime import timedelta
from typing import Any

from django.conf import settings
from django.db import transaction
from django.utils import timezone

from backups.changes import request_summary
from backups.models import BackupJob
from core import keys
from core.models import Worker
from core.signing import sign_task
from core.workers import driver_catalogue
from devicevault.celery import app as celery_app
from devicevault_protocol import signing
from devicevault_protocol.jobs import (
    EVENT_COLLECTED,
    EVENT_DELETE_FAILED,
    EVENT_DELETED,
    EVENT_FAILED,
    EVENT_RETRYING,
    EVENT_STARTED,
    EVENT_STORED,
    STAGE_STORE,
)
from devicevault_protocol.names import COLLECT_TASK, STORE_TASK, collection_queue_name
from devicevault_protocol.registration import ROLE_COLLECTOR, ROLE_STORAGE, STATUS_APPROVED
from storage.service import target_spec, target_workers

logger = logging.getLogger('devicevault.jobs')

# Events can wait in the queue while the orchestrator is down.
EVENT_MAX_AGE = timedelta(days=1)
MAX_LOG_ENTRIES = 500


class JobError(Exception):
    """A device cannot be backed up as configured."""


# --- creating and dispatching -------------------------------------------------------


def create_job(device, *, trigger=BackupJob.TRIGGER_MANUAL, user=None, schedule=None) -> tuple[BackupJob, bool]:
    """Queue a backup of ``device``. Returns ``(job, created)``.

    If the device already has an active job, that job is returned instead, so
    repeated "backup now" clicks and overlapping schedules do not pile up.
    """
    if not device.backup_method:
        raise JobError('the device is not polled (it only pushes its backups)')
    if not device.collection_group:
        raise JobError('the device has no collection group, so no collector can back it up')
    target = device.storage_target
    if not target:
        raise JobError('the device has no storage target')
    # Nobody would consume the job's tasks. (With payload encryption, secrets are
    # also sealed to the workers approved now; one approved later cannot open them.)
    if not collectors(device.collection_group):
        raise JobError(f'no approved collector serves collection group "{device.collection_group.name}"')
    if not target_workers(target):
        raise JobError(f'storage target "{target.name}" has no approved storage worker')

    with transaction.atomic():
        active = (
            BackupJob.objects.select_for_update()
            .filter(device=device, state__in=BackupJob.ACTIVE_STATES)
            .order_by('-created_at')
            .first()
        )
        if active:
            return active, False
        driver = driver_catalogue().get(device.backup_method)
        job = BackupJob.objects.create(
            device=device,
            trigger=trigger,
            requested_by=user if user and user.is_authenticated else None,
            schedule=schedule,
            driver=device.backup_method,
            # Provisional (it picks the file extension); the collector's report is authoritative.
            is_binary=bool(driver and driver['is_binary']),
            storage_target=target,
            storage_driver=target.driver,
        )
    transaction.on_commit(lambda: dispatch(job))
    return job, True


def collectors(group) -> list[Worker]:
    return list(Worker.objects.filter(status=STATUS_APPROVED, role=ROLE_COLLECTOR, collection_groups=group))


def _device_key(device) -> str:
    slug = re.sub(r'[^a-z0-9]+', '-', device.name.lower()).strip('-')[:64] or 'device'
    return f'{device.pk}-{slug}'


def store_spec(job: BackupJob) -> dict[str, Any]:
    """The orchestrator-signed half of a ``job.store`` task (the other half is the staged blob)."""
    return target_spec(
        job.storage_target,
        job_id=str(job.id),
        name={
            'device_key': _device_key(job.device),
            'job_id': str(job.id),
            'timestamp': job.created_at.strftime('%Y%m%dT%H%M%SZ'),
            'extension': '.bin' if job.is_binary else '.cfg',
        },
    )


def send_store(job: BackupJob, blob: dict[str, Any]) -> None:
    """Have the job's storage target store a blob the orchestrator was told about (pushed backups)."""
    celery_app.send_task(STORE_TASK, args=[sign_task(store_spec(job)), blob], queue=job.storage_target.queue)


def collect_payload(job: BackupJob) -> dict[str, Any]:
    device = job.device
    store = store_spec(job)
    collect = {
        'job_id': str(job.id),
        'device': {'id': device.pk, 'name': device.name, 'address': device.ip_address},
        'driver': job.driver,
        'driver_params': device.driver_params or {},
        'timeout': settings.DEVICEVAULT_COLLECT_TIMEOUT_SEC,
        'encryption': keys.vault_public(),
        'store': {'queue': job.storage_target.queue, 'envelope': sign_task(store)},
    }
    credentials = device.credential.data if device.credential else {}
    keys.add_secret(collect, 'credentials', credentials, collectors(device.collection_group))
    return collect


def dispatch(job: BackupJob) -> None:
    queue = collection_queue_name(job.device.collection_group.rabbitmq_queue_id)
    celery_app.send_task(COLLECT_TASK, args=[sign_task(collect_payload(job))], queue=queue)


# --- events ------------------------------------------------------------------------------


class EventRejected(Exception):
    pass


def _verified_event(envelope: Any) -> tuple[dict[str, Any], Worker]:
    try:
        claimed = signing.peek(envelope)
        worker_id = str(uuid.UUID(str(claimed.get('worker_id'))))
        if envelope.get('signer') != worker_id:
            raise EventRejected('signer does not match worker_id')
        worker = Worker.objects.filter(pk=worker_id, status=STATUS_APPROVED).first()
        if worker is None:
            raise EventRejected('job events are only accepted from approved workers')
        payload = signing.verify(envelope, signing.public_key_from_b64(worker.signing_key), max_age=EVENT_MAX_AGE)
        uuid.UUID(str(payload.get('job_id')))
    except (EventRejected, signing.SignatureError, ValueError, TypeError, AttributeError) as exc:
        logger.warning('job_event_rejected', extra={'reason': str(exc)})
        raise EventRejected(str(exc)) from exc
    return payload, worker


def handle_job_event(envelope: Any) -> BackupJob | None:
    payload, worker = _verified_event(envelope)
    with transaction.atomic():
        job = BackupJob.objects.select_for_update().select_related('device').filter(pk=payload['job_id']).first()
        if job is None:
            logger.warning('job_event_for_unknown_job', extra={'job_id': payload['job_id']})
            return None
        if payload.get('event') in (EVENT_DELETED, EVENT_DELETE_FAILED):
            _apply_deletion(job, payload, worker)
            job.save()
            return job
        was = job.state
        _apply(job, payload, worker)
        job.save()
        if job.state in BackupJob.TERMINAL_STATES:
            _record_on_device(job)
        if job.state == BackupJob.STORED and was != BackupJob.STORED:
            transaction.on_commit(lambda: request_summary(job))
    return job


def _apply(job: BackupJob, payload: dict[str, Any], worker: Worker) -> None:
    event = payload.get('event')
    now = timezone.now()
    stage = payload.get('stage')
    entries = [e for e in payload.get('log') or [] if isinstance(e, dict)]
    job.log = (job.log + entries)[-MAX_LOG_ENTRIES:]

    if job.state in (BackupJob.STORED, BackupJob.FAILED):
        return  # late or duplicate event for a finished job; keep its log only

    if event == EVENT_STARTED:
        if stage == STAGE_STORE:
            job.storage_worker = worker.name
            if job.state != BackupJob.STORED:
                job.state = BackupJob.STORING
        else:
            job.collector = worker.name
            job.attempts = max(job.attempts, int(payload.get('attempt') or 1))
            job.error = ''  # a new attempt; the previous one's error is in the log
            job.started_at = job.started_at or now
            if job.state == BackupJob.QUEUED:
                job.state = BackupJob.COLLECTING
    elif event == EVENT_RETRYING:
        job.error = str(payload.get('error') or '')
    elif event == EVENT_COLLECTED:
        job.collected_sha256 = str(payload.get('sha256') or '')
        job.size_bytes = int(payload.get('size') or 0)
        job.is_binary = bool(payload.get('is_binary'))
        job.encrypted = bool(payload.get('encrypted'))
        job.collect_duration_ms = int(payload.get('duration_ms') or 0)
        job.collected_at = now
        job.error = ''
        if job.state in (BackupJob.QUEUED, BackupJob.COLLECTING, BackupJob.TIMED_OUT):
            job.state = BackupJob.COLLECTED
        _finish_if_complete(job, now)
    elif event == EVENT_STORED:
        job.stored_sha256 = str(payload.get('sha256') or '')
        job.storage_ref = str(payload.get('storage_ref') or '')
        job.store_duration_ms = int(payload.get('duration_ms') or 0)
        job.storage_worker = worker.name
        _finish_if_complete(job, now)
    elif event == EVENT_FAILED:
        job.state = BackupJob.FAILED
        job.error = str(payload.get('error') or 'failed')
        job.finished_at = now


def _apply_deletion(job: BackupJob, payload: dict[str, Any], worker: Worker) -> None:
    """A storage worker reports on a deletion retention asked for (see backups.retention)."""
    if not job.prune_requested_at or job.pruned_at:
        logger.warning('deletion_event_ignored', extra={'job_id': str(job.id), 'reason': 'no deletion pending'})
        return
    if not job.storage_target.workers.filter(pk=worker.pk, role=ROLE_STORAGE).exists():
        logger.warning('deletion_event_ignored', extra={'job_id': str(job.id), 'reason': 'not its storage worker'})
        return
    entries = [e for e in payload.get('log') or [] if isinstance(e, dict)]
    if payload['event'] == EVENT_DELETED:
        job.pruned_at = timezone.now()
    else:
        # Still stored: readable again, and retention will ask again on a later pass.
        job.prune_requested_at = None
        error = str(payload.get('error') or 'failed')
        entries.append(_log_entry('ERROR', f'retention could not delete the backup: {error}'))
        logger.warning('retention_delete_failed', extra={'job_id': str(job.id), 'error': error})
    job.log = (job.log + entries)[-MAX_LOG_ENTRIES:]


def _log_entry(severity: str, message: str) -> dict[str, str]:
    return {'source': 'retention', 'timestamp': timezone.now().isoformat(), 'severity': severity, 'message': message}


def _finish_if_complete(job: BackupJob, now) -> None:
    """A job is stored once both sides agree on the content hash, in either order."""
    if not (job.collected_sha256 and job.stored_sha256):
        if job.stored_sha256:
            job.state = BackupJob.STORING  # stored, waiting for the collector's report
        return
    if job.collected_sha256 == job.stored_sha256:
        job.state = BackupJob.STORED
        job.error = ''
    else:
        job.state = BackupJob.FAILED
        job.error = 'the stored backup does not match what the collector collected'
    job.finished_at = now


def _record_on_device(job: BackupJob) -> None:
    from devices.models import Device

    Device.objects.filter(pk=job.device_id).update(
        last_backup_time=job.finished_at, last_backup_status='success' if job.succeeded else 'failure'
    )


# --- timeouts ----------------------------------------------------------------------------


def expire_stale_jobs(now=None) -> int:
    """Mark jobs that have been active for too long as timed out."""
    now = now or timezone.now()
    cutoff = now - timedelta(minutes=settings.DEVICEVAULT_JOB_TIMEOUT_MIN)
    stale = list(BackupJob.objects.filter(state__in=BackupJob.ACTIVE_STATES, created_at__lt=cutoff))
    for job in stale:
        job.state = BackupJob.TIMED_OUT
        job.error = f'no result within {settings.DEVICEVAULT_JOB_TIMEOUT_MIN} minutes'
        job.finished_at = now
        job.save(update_fields=['state', 'error', 'finished_at'])
        _record_on_device(job)
    return len(stale)
