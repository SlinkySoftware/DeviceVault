"""Handling the signed events receivers send (see devicevault_protocol.push).

A ``received`` event becomes a BackupJob that is already collected, and the
orchestrator sends the store task; from there it is the normal pipeline. The
receiver's checks are repeated here, since the device may have changed while
the file was on its way.
"""

import fnmatch
import logging
import uuid
from datetime import datetime, timedelta
from typing import Any

from django.conf import settings
from django.db import transaction
from django.utils import timezone
from redis import Redis

from audit.log import record
from audit.models import AuditLog
from backups.jobs import MAX_LOG_ENTRIES, send_store
from backups.models import BackupJob
from core.models import Worker
from devicevault_protocol import blobs, signing
from devicevault_protocol.jobs import blob_key
from devicevault_protocol.push import (
    EVENT_RECEIVED,
    EVENT_REJECTED,
    PROTOCOLS,
    REASON_DEVICE_CHANGED,
    REASON_ERROR,
    REASONS,
    normalise_address,
)
from devicevault_protocol.registration import ROLE_RECEIVER, STATUS_APPROVED
from push.models import PushRejection

logger = logging.getLogger('devicevault.push')

# Received events wait in the queue while the orchestrator is down; staged blobs last a day.
EVENT_MAX_AGE = timedelta(days=1)


class EventRejected(Exception):
    pass


def _verified(envelope: Any) -> tuple[dict[str, Any], Worker]:
    try:
        claimed = signing.peek(envelope)
        worker_id = str(uuid.UUID(str(claimed.get('worker_id'))))
        if envelope.get('signer') != worker_id:
            raise EventRejected('signer does not match worker_id')
        worker = Worker.objects.filter(pk=worker_id, status=STATUS_APPROVED, role=ROLE_RECEIVER).first()
        if worker is None:
            raise EventRejected('push events are only accepted from approved receivers')
        payload = signing.verify(envelope, signing.public_key_from_b64(worker.signing_key), max_age=EVENT_MAX_AGE)
        if payload.get('protocol') not in PROTOCOLS:
            raise EventRejected(f'unknown protocol {payload.get("protocol")!r}')
    except (EventRejected, signing.SignatureError, ValueError, TypeError, AttributeError) as exc:
        logger.warning('push_event_rejected', extra={'reason': str(exc)})
        raise EventRejected(str(exc)) from exc
    return payload, worker


def handle_push_event(envelope: Any) -> BackupJob | PushRejection | None:
    payload, worker = _verified(envelope)
    if payload.get('event') == EVENT_RECEIVED:
        return _received(payload, worker)
    if payload.get('event') == EVENT_REJECTED:
        reason = payload.get('reason')
        return record_rejection(
            worker,
            source_ip=str(payload.get('source_ip') or ''),
            protocol=payload['protocol'],
            reason=reason if reason in REASONS else REASON_ERROR,
            filename=str(payload.get('filename') or ''),
            detail=str(payload.get('detail') or ''),
            at=_timestamp(payload.get('at')),
        )
    logger.warning('push_event_unknown', extra={'event': payload.get('event')})
    return None


def _timestamp(value: Any) -> datetime:
    try:
        at = datetime.fromisoformat(str(value))
        return at if timezone.is_aware(at) else timezone.now()
    except ValueError:
        return timezone.now()


def device_problem(device, protocol: str, source_ip: str, filename: str) -> str | None:
    """Why ``device`` no longer accepts this push (None if it does)."""
    if device is None:
        return 'the device no longer exists'
    if not device.enabled:
        return 'the device is disabled'
    if device.push_mode != protocol:
        return f'the device does not push over {protocol}'
    if normalise_address(device.ip_address) != source_ip:
        return f'the device address is now {device.ip_address}'
    if device.push_filename_pattern and not fnmatch.fnmatchcase(filename, device.push_filename_pattern):
        return f'the filename does not match {device.push_filename_pattern}'
    if device.storage_target is None:
        return 'the device has no storage target'
    return None


def _received(payload: dict[str, Any], worker: Worker) -> BackupJob | None:
    from devices.models import Device

    job_id = str(uuid.UUID(str(payload.get('job_id'))))
    blob = payload.get('blob')
    if not isinstance(blob, dict) or blob.get('key') != blob_key(job_id) or not blob.get('sha256'):
        logger.warning('push_event_bad_blob', extra={'job_id': job_id})
        return None
    protocol = payload['protocol']
    filename = str(payload.get('filename') or '')[:255]
    try:
        source_ip = normalise_address(str(payload.get('source_ip')))
    except ValueError:
        source_ip = str(payload.get('source_ip'))[:64]

    with transaction.atomic():
        if BackupJob.objects.filter(pk=job_id).exists():
            return None  # redelivered event
        device = Device.objects.select_related('storage_target').filter(pk=payload.get('device_id')).first()
        problem = device_problem(device, protocol, source_ip, filename)
        if problem:
            _discard(blob['key'])
            record_rejection(
                worker,
                source_ip=source_ip,
                protocol=protocol,
                reason=REASON_DEVICE_CHANGED,
                filename=filename,
                detail=problem,
            )
            return None

        now = timezone.now()
        entries = [e for e in payload.get('log') or [] if isinstance(e, dict)][-MAX_LOG_ENTRIES:]
        job = BackupJob.objects.create(
            id=job_id,
            device=device,
            state=BackupJob.COLLECTED,
            trigger=BackupJob.TRIGGER_PUSH,
            driver=f'push:{protocol}',
            source_filename=filename,
            is_binary=bool(payload.get('is_binary')),
            collector=worker.name,
            storage_target=device.storage_target,
            storage_driver=device.storage_target.driver,
            collected_sha256=str(blob['sha256']),
            size_bytes=int(blob.get('size') or 0),
            encrypted=bool(payload.get('encrypted')),
            attempts=1,
            log=entries,
            started_at=now,
            collected_at=now,
            collect_duration_ms=int(payload.get('duration_ms') or 0),
        )
    transaction.on_commit(lambda: send_store(job, blob))
    logger.info('push_received', extra={'job_id': job_id, 'device_id': device.pk, 'receiver': worker.name})
    return job


def _discard(key: str) -> None:
    try:
        blobs.delete(Redis.from_url(settings.DEVICEVAULT_BUS.redis_url), key)
    except Exception:  # it expires anyway
        logger.exception('push_blob_discard_failed', extra={'key': key})


def record_rejection(
    worker: Worker, *, source_ip: str, protocol: str, reason: str, filename: str = '', detail: str = '', at=None
) -> PushRejection:
    rejection = PushRejection.objects.create(
        worker=worker,
        at=at or timezone.now(),
        source_ip=source_ip[:64],
        protocol=protocol,
        reason=reason,
        filename=filename[:255],
        detail=detail[:255],
    )
    PushRejection.objects.filter(worker=worker, at__lt=timezone.now() - PushRejection.MAX_AGE).delete()
    stale = PushRejection.objects.filter(worker=worker).values_list('pk', flat=True)[PushRejection.KEEP :]
    PushRejection.objects.filter(pk__in=list(stale)).delete()
    record(
        None,
        'push.rejected',
        resource=source_ip,
        outcome=AuditLog.DENIED,
        details={
            'receiver': worker.name,
            'protocol': protocol,
            'reason': reason,
            'filename': filename,
            'detail': detail,
        },
        actor_name=worker.name,
    )
    return rejection
