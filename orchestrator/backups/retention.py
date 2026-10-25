"""Retention: deleting the stored backups a device's retention policy no longer keeps.

The scheduler's leader runs ``run_retention`` every ``DV_RETENTION_INTERVAL_MIN``.
For each policy it works out which backups of its devices have expired
(``expired_jobs``, see ``RetentionPolicy`` for the rules) and either reports them
(dry run) or sends signed ``storage.delete`` tasks to their storage targets. The
storage worker reports each deletion as a job event (``backups.jobs``); the job
row stays, marked pruned, as the record of what was kept and when it went.

Safety rails:

- the newest ``min_backups`` (at least one) of a device are always kept;
- pinned backups are never counted or deleted;
- backups on a target whose driver does not delete (git) are kept;
- new policies start in dry run, which audits what would go instead;
- at most ``MAX_DELETIONS_PER_PASS`` deletions are requested per pass.
"""

import hashlib
import logging
from collections import defaultdict
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from itertools import batched
from typing import Any

from django.db import transaction
from django.utils import timezone

from audit.log import record
from backups.models import BackupJob
from core.signing import sign_task
from core.workers import storage_driver_catalogue
from devicevault.celery import app as celery_app
from devicevault_protocol.names import DELETE_TASK
from policies.models import RetentionPolicy
from storage.service import target_spec, target_workers

logger = logging.getLogger('devicevault.retention')

ACTOR = 'retention'
# A deletion no worker reported on is asked for again after this long (deleting is idempotent).
PRUNE_RETRY_AFTER = timedelta(days=1)
MAX_DELETIONS_PER_PASS = 1000
ITEMS_PER_TASK = 100
AUDIT_MAX_JOBS = 100


def expired_jobs(device, policy: RetentionPolicy, now: datetime) -> list[BackupJob]:
    """The stored backups of ``device`` that ``policy`` no longer keeps, newest first."""
    cutoff = now - timedelta(days=policy.max_days) if policy.max_days is not None else None
    jobs = (
        BackupJob.objects.filter(device=device, state=BackupJob.STORED, pinned=False, pruned_at__isnull=True)
        .exclude(storage_ref='')
        .select_related('device', 'storage_target')
        .order_by('-created_at')
    )
    expired = []
    total = 0
    for index, job in enumerate(jobs):
        total += job.size_bytes or 0
        if index < max(policy.min_backups, 1):
            continue
        if (
            (policy.max_backups is not None and index >= policy.max_backups)
            or (cutoff is not None and job.created_at < cutoff)
            or (policy.max_size_bytes is not None and total > policy.max_size_bytes)
        ):
            expired.append(job)
    return expired


@dataclass
class Plan:
    """What a policy expires now."""

    # Expired backups retention can delete, by device. Those on a target no worker
    # serves right now are included; they are sent once a worker is back.
    expired: dict[Any, list[BackupJob]] = field(default_factory=dict)
    # Expired, but on a target whose driver keeps everything (git).
    kept: int = 0

    @property
    def jobs(self) -> list[BackupJob]:
        return [job for jobs in self.expired.values() for job in jobs]

    @property
    def bytes(self) -> int:
        return sum(job.size_bytes or 0 for job in self.jobs)


def plan(policy: RetentionPolicy, now: datetime | None = None) -> Plan:
    """Which backups of the devices using ``policy`` have expired."""
    from devices.models import Device

    now = now or timezone.now()
    # Only a driver that says so keeps everything; one no worker offers now is just unavailable.
    keeping = {key for key, driver in storage_driver_catalogue().items() if not driver['deletes']}
    result = Plan()
    for device in Device.objects.filter(retention_policy=policy).order_by('name'):
        jobs = expired_jobs(device, policy, now)
        deletable = [job for job in jobs if job.storage_target.driver not in keeping]
        result.kept += len(jobs) - len(deletable)
        if deletable:
            result.expired[device] = deletable
    return result


def _digest(jobs: list[BackupJob]) -> str:
    return hashlib.sha256(','.join(sorted(str(job.id) for job in jobs)).encode()).hexdigest()


def _summary(expired: dict[Any, list[BackupJob]]) -> list[dict[str, Any]]:
    return [{'device': device.pk, 'device_name': device.name, 'backups': len(jobs)} for device, jobs in expired.items()]


def request_deletion(jobs: list[BackupJob], now: datetime) -> list[BackupJob]:
    """Mark ``jobs`` as being pruned and send their targets the delete tasks. Returns the jobs sent."""
    by_target = defaultdict(list)
    for job in jobs:
        by_target[job.storage_target].append(job)
    sent = []
    with transaction.atomic():
        for target, target_jobs in by_target.items():
            if not target_workers(target):
                continue  # nobody would delete them; try again next pass
            # Re-checked under lock: a backup pinned since planning stays.
            ids = list(
                BackupJob.objects.select_for_update()
                .filter(pk__in=[job.pk for job in target_jobs], pinned=False, pruned_at__isnull=True)
                .values_list('pk', flat=True)
            )
            BackupJob.objects.filter(pk__in=ids).update(prune_requested_at=now)
            locked = set(ids)
            chosen = [job for job in target_jobs if job.pk in locked]
            for chunk in batched(chosen, ITEMS_PER_TASK, strict=False):
                items = [{'job_id': str(job.id), 'storage_ref': job.storage_ref} for job in chunk]
                envelope = sign_task(target_spec(target, items=items))
                transaction.on_commit(lambda envelope=envelope, queue=target.queue: _send(envelope, queue))
            sent += chosen
    return sent


def _send(envelope: dict[str, Any], queue: str) -> None:
    celery_app.send_task(DELETE_TASK, args=[envelope], queue=queue, expires=int(PRUNE_RETRY_AFTER.total_seconds()))


def apply_policy(policy: RetentionPolicy, now: datetime, budget: int) -> int:
    """One retention pass of ``policy``. Returns how many deletions it requested."""
    found = plan(policy, now)
    jobs = found.jobs
    result: dict[str, Any] = {
        'dry_run': policy.dry_run,
        'expired': len(jobs),
        'expired_bytes': found.bytes,
        'kept_undeletable': found.kept,
        'requested': 0,
    }
    if policy.dry_run:
        # Audited when what would go changes, not on every pass.
        result['digest'] = _digest(jobs)
        if jobs and result['digest'] != policy.last_result.get('digest'):
            record(
                None,
                'retention.dry_run',
                resource=str(policy.pk),
                details={'policy': policy.name, **result, 'devices': _summary(found.expired)},
                actor_name=ACTOR,
            )
    else:
        stale = now - PRUNE_RETRY_AFTER
        due = [job for job in jobs if not job.prune_requested_at or job.prune_requested_at < stale][:budget]
        sent = request_deletion(due, now)
        result['requested'] = len(sent)
        if sent:
            by_device = defaultdict(list)
            for job in sent:
                by_device[job.device].append(job)
            record(
                None,
                'retention.delete',
                resource=str(policy.pk),
                details={
                    'policy': policy.name,
                    **result,
                    'requested_bytes': sum(job.size_bytes or 0 for job in sent),
                    'devices': _summary(by_device),
                    'jobs': [str(job.id) for job in sent[:AUDIT_MAX_JOBS]],
                },
                actor_name=ACTOR,
            )
    RetentionPolicy.objects.filter(pk=policy.pk).update(last_run_at=now, last_result=result)
    return result['requested']


def run_retention(now: datetime | None = None, leading: Callable[[], bool] | None = None) -> int:
    """Apply every retention policy. Returns how many deletions were requested.

    ``leading`` is asked before each policy; once it says no, nothing more is done.
    """
    now = now or timezone.now()
    requested = 0
    for policy in RetentionPolicy.objects.order_by('pk'):
        if leading is not None and not leading():
            logger.warning('scheduler_lease_lost', extra={'policy': policy.pk})
            break
        try:
            requested += apply_policy(policy, now, MAX_DELETIONS_PER_PASS - requested)
        except Exception:
            logger.exception('retention_failed', extra={'policy': policy.pk})
    return requested
