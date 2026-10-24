"""Worker registration, approval and assignment.

See devicevault_protocol.registration for the message formats.
"""

import logging
import uuid
from datetime import timedelta
from typing import Any

from django.conf import settings
from django.db import IntegrityError, transaction
from django.utils import timezone

from core.models import Worker
from core.signing import public_key, signing_key
from devicevault_protocol import signing
from devicevault_protocol.registration import (
    ASSIGNMENT,
    ROLE_COLLECTOR,
    ROLE_RECEIVER,
    ROLE_STORAGE,
    STATUS_APPROVED,
    STATUS_PENDING,
    STATUS_REVOKED,
    control_queue_name,
)
from devicevault_protocol.tasks import ORCHESTRATOR_SIGNER

logger = logging.getLogger('devicevault.workers')

# Events older than this are discarded (they also expire in the queue).
EVENT_MAX_AGE = timedelta(minutes=10)


class EventRejected(Exception):
    """A worker event failed validation and was ignored."""


# --- assignments -----------------------------------------------------------------


def assignment_payload(worker: Worker) -> dict[str, Any]:
    approved = worker.status == STATUS_APPROVED
    payload = {
        'type': ASSIGNMENT,
        'worker_id': str(worker.id),
        'version': worker.desired_version,
        'status': worker.status,
        'role': worker.role if approved else '',
        'queues': worker.assigned_queues(),
        'orchestrator_key': public_key(),
    }
    if approved and worker.role == ROLE_RECEIVER:
        from push.service import receiver_assignment

        payload['receiver'] = receiver_assignment(worker)
    return payload


def publish_control(worker_id: str, envelope: dict[str, Any]) -> None:
    """Send a control message to the worker's control queue (dropped if it is offline)."""
    from devicevault.celery import app

    with app.producer_or_acquire() as producer:
        producer.publish(
            envelope,
            exchange='',
            routing_key=control_queue_name(worker_id),
            serializer='json',
            retry=True,
            retry_policy={'max_retries': 3, 'interval_start': 0.2, 'interval_step': 0.5, 'interval_max': 2},
        )


def push_assignment(worker: Worker) -> None:
    """Send the worker its current assignment. Pending workers get nothing yet."""
    if worker.status == STATUS_PENDING:
        return
    envelope = signing.sign(assignment_payload(worker), signing_key(), ORCHESTRATOR_SIGNER)
    publish_control(str(worker.id), envelope)


def update_assignment(worker: Worker, **changes: Any) -> Worker:
    """Apply assignment changes, bump the version and push it to the worker.

    ``collection_groups`` and ``storage_targets`` (if given) are lists of model instances.
    """
    groups = changes.pop('collection_groups', None)
    targets = changes.pop('storage_targets', None)
    with transaction.atomic():
        for field, value in changes.items():
            setattr(worker, field, value)
        worker.desired_version += 1
        worker.save()
        if groups is not None:
            worker.collection_groups.set(groups)
        if targets is not None:
            worker.storage_targets.set(targets)
    push_assignment(worker)
    return worker


def approve(worker: Worker, *, role: str, user=None, collection_groups=None, storage_targets=None) -> Worker:
    """Approve ``worker`` with a role. Check storage targets with ``approval_target_problems`` first."""
    if role == ROLE_RECEIVER:
        from push.service import settings_for

        settings_for(worker)  # listens for nothing until an administrator enables a protocol
    return update_assignment(
        worker,
        status=STATUS_APPROVED,
        role=role,
        approved_at=timezone.now(),
        approved_by=user,
        collection_groups=list(collection_groups or []) if role == ROLE_COLLECTOR else [],
        storage_targets=list(storage_targets or []) if role == ROLE_STORAGE else [],
    )


def revoke(worker: Worker) -> Worker:
    return update_assignment(worker, status=STATUS_REVOKED)


def set_target_workers(target, workers: list[Worker]) -> None:
    """Assign a storage target to exactly ``workers`` and reassign everyone affected."""
    with transaction.atomic():
        before = set(target.workers.all())
        target.workers.set(workers)
    for worker in before ^ set(workers):
        update_assignment(worker)


def release_target(target) -> None:
    """A storage target is about to be deleted: take its queue away from its workers."""
    affected = list(target.workers.all())
    target.workers.clear()
    for worker in affected:
        update_assignment(worker)


def offered_storage_drivers(worker: Worker) -> dict[str, dict[str, Any]]:
    drivers = (worker.capabilities or {}).get('storage_drivers') or []
    return {d['key']: d for d in drivers if isinstance(d, dict) and d.get('key')}


def _single_worker_problem(driver_key: str, workers) -> list[str]:
    if len(workers) > 1 and any(not offered_storage_drivers(w).get(driver_key, {}).get('shareable') for w in workers):
        return [f'the "{driver_key}" driver stores on one worker\'s own volume, so only one worker can serve a target']
    return []


def target_worker_problems(driver_key: str, workers: list[Worker]) -> list[str]:
    """Why ``workers`` cannot serve a storage target using ``driver_key`` (empty if they can)."""
    problems = []
    for worker in workers:
        if worker.status != STATUS_APPROVED or worker.role != ROLE_STORAGE:
            problems.append(f'{worker.name} is not an approved storage worker')
        elif driver_key not in offered_storage_drivers(worker):
            problems.append(f'{worker.name} does not offer the "{driver_key}" storage driver')
    return problems or _single_worker_problem(driver_key, workers)


def approval_target_problems(worker: Worker, targets) -> list[str]:
    """Why ``worker`` cannot be approved to serve ``targets`` (empty if it can)."""
    problems = []
    for target in targets:
        if target.driver not in offered_storage_drivers(worker):
            problems.append(f'{worker.name} does not offer the "{target.driver}" storage driver ({target.name})')
            continue
        sharing = [worker, *target.workers.exclude(pk=worker.pk)]
        problems += [f'{target.name}: {p}' for p in _single_worker_problem(target.driver, sharing)]
    return problems


def bump_collection_group(group) -> None:
    """A collection group's queue changed: reassign every worker serving it."""
    for worker in Worker.objects.filter(collection_groups=group, status=STATUS_APPROVED):
        update_assignment(worker)


# --- events --------------------------------------------------------------------------


def handle_event(envelope: Any) -> Worker:
    """Record a signed register/heartbeat event and reconcile the assignment.

    The first event from a worker fixes its signing key; later events must be
    signed with the same key, so a worker id cannot be taken over.
    """
    try:
        claimed = signing.peek(envelope)
        worker_id = str(uuid.UUID(str(claimed.get('worker_id'))))
        if envelope.get('signer') != worker_id:
            raise EventRejected('signer does not match worker_id')
        existing = Worker.objects.filter(pk=worker_id).first()
        key = existing.signing_key if existing else claimed.get('signing_key')
        if not isinstance(key, str) or not key:
            raise EventRejected('no signing key')
        if existing and claimed.get('signing_key') != existing.signing_key:
            raise EventRejected('signing key differs from the one registered')
        payload = signing.verify(envelope, signing.public_key_from_b64(key), max_age=EVENT_MAX_AGE)
    except (EventRejected, signing.SignatureError, ValueError, TypeError, AttributeError) as exc:
        logger.warning('worker_event_rejected', extra={'reason': str(exc)})
        raise EventRejected(str(exc)) from exc

    reported = {
        'name': str(payload.get('name') or worker_id)[:255],
        'celery_hostname': str(payload.get('celery_hostname') or '')[:255],
        'hostname': str(payload.get('hostname') or '')[:255],
        'pid': payload.get('pid') if isinstance(payload.get('pid'), int) else None,
        'version': str(payload.get('version') or '')[:64],
        'capabilities': payload.get('capabilities') if isinstance(payload.get('capabilities'), dict) else {},
        'applied_version': max(0, int(payload.get('applied_version') or 0)),
        'applied_queues': [str(q) for q in payload.get('queues') or []],
        'runtime': {'receiver': payload['receiver']} if isinstance(payload.get('receiver'), dict) else {},
        'pinned_orchestrator_key': str(payload.get('orchestrator_key') or '')[:64],
        'last_seen_at': timezone.now(),
    }

    if existing:
        Worker.objects.filter(pk=worker_id).update(**reported)
        worker = Worker.objects.get(pk=worker_id)
    else:
        try:
            worker = Worker.objects.create(
                id=worker_id,
                signing_key=key,
                encryption_key=str(payload.get('encryption_key') or '')[:64],
                fingerprint=signing.fingerprint(key),
                # A worker that was forgotten (or a restored database) may already be
                # ahead; start from its version so the next assignment is newer.
                desired_version=reported['applied_version'],
                **reported,
            )
            logger.info('worker_registered', extra={'worker_id': worker_id, 'fingerprint': worker.fingerprint})
        except IntegrityError:
            # Another orchestrator node registered it concurrently.
            return handle_event(envelope)

    if worker.status == STATUS_PENDING:
        return worker
    if worker.applied_version > worker.desired_version:
        # The worker applied a newer version than we know about (e.g. after a
        # database restore); it would ignore ours as stale, so jump past it.
        Worker.objects.filter(pk=worker.pk).update(desired_version=worker.applied_version + 1)
        worker.refresh_from_db()
    if worker.applied_version != worker.desired_version:
        push_assignment(worker)
    elif worker.role == ROLE_RECEIVER:
        from push.service import needs_update

        if needs_update(worker):
            update_assignment(worker)
    return worker


def is_online(worker: Worker, now=None) -> bool:
    if not worker.last_seen_at:
        return False
    cutoff = (now or timezone.now()) - timedelta(seconds=settings.DEVICEVAULT_WORKER_ONLINE_TIMEOUT_SEC)
    return worker.last_seen_at >= cutoff


def _version_key(version: str) -> tuple:
    """Orders '2' < '10' and keeps mixed parts ('1.0b') comparable."""
    return tuple((0, int(part), '') if part.isdigit() else (1, 0, part) for part in version.split('.'))


def _catalogue(role: str, capability: str, flag: str) -> dict[str, dict[str, Any]]:
    """Drivers advertised under ``capabilities[capability]`` by approved workers of ``role``.

    Each entry: key, name, description, ``flag`` (is_binary or shareable),
    params_schema (JSON schema of its settings), ``workers`` (how many
    approved workers offer it) and ``versions``. When workers run different
    versions of a driver, the newest one describes it.
    """
    catalogue: dict[str, dict[str, Any]] = {}
    for capabilities in Worker.objects.filter(status=STATUS_APPROVED, role=role).values_list('capabilities', flat=True):
        for driver in (capabilities or {}).get(capability, []):
            if not isinstance(driver, dict) or not driver.get('key'):
                continue
            version = str(driver.get('version') or '1')
            entry = catalogue.get(driver['key'])
            if entry is None or _version_key(version) > _version_key(entry['version']):
                schema = driver.get('params_schema')
                catalogue[driver['key']] = entry = {
                    'key': driver['key'],
                    'name': driver.get('name') or driver['key'],
                    'description': driver.get('description', ''),
                    flag: bool(driver.get(flag)),
                    'params_schema': schema if isinstance(schema, dict) else None,
                    'version': version,
                    'workers': entry['workers'] if entry else 0,
                    'versions': entry['versions'] if entry else set(),
                }
            entry['workers'] += 1
            entry['versions'].add(version)
    for entry in catalogue.values():
        entry['versions'] = sorted(entry['versions'], key=_version_key)
    return dict(sorted(catalogue.items()))


def driver_catalogue() -> dict[str, dict[str, Any]]:
    """Collector drivers offered by approved collectors, by key (see ``_catalogue``)."""
    return _catalogue(ROLE_COLLECTOR, 'collector_drivers', 'is_binary')


def storage_driver_catalogue() -> dict[str, dict[str, Any]]:
    """Storage drivers offered by approved storage workers, by key (see ``_catalogue``)."""
    return _catalogue(ROLE_STORAGE, 'storage_drivers', 'shareable')
