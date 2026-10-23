"""The scheduler: runs due backup schedules and expires stuck jobs.

Every orchestrator node may run it; only the holder of a Redis lease acts. The
leader renews the lease every tick and releases it on a clean shutdown, so a
standby takes over at its next tick; if the leader dies instead, the lease
expires first (``LEASE_SECONDS``). The leader also re-checks the lease before
each due schedule, so a leader that stalled past its lease stops scheduling.
The leader also prunes expired sign-in sessions, hourly.
"""

import logging
import uuid
from collections.abc import Callable
from datetime import datetime, timedelta

from django.db import transaction
from django.utils import timezone
from redis import Redis

from accounts.sessions import prune_expired
from backups.jobs import JobError, create_job, expire_stale_jobs
from backups.models import BackupJob
from policies.models import BackupSchedule

logger = logging.getLogger('devicevault.scheduler')

LEASE_KEY = 'dv:scheduler:leader'
LEASE_SECONDS = 60
SESSION_PRUNE_INTERVAL = timedelta(hours=1)
_last_session_prune: datetime | None = None

# Extend the lease only if we still hold it (compare-and-extend).
_RENEW = """
if redis.call('get', KEYS[1]) == ARGV[1] then
    return redis.call('pexpire', KEYS[1], ARGV[2])
end
return 0
"""


class Leadership:
    """This node's claim on the scheduler lease."""

    def __init__(self, redis: Redis, node: str | None = None, lease_seconds: int = LEASE_SECONDS):
        self.redis = redis
        self.token = f'{node or "node"}:{uuid.uuid4().hex}'
        self.lease_seconds = lease_seconds
        self._renew = redis.register_script(_RENEW)

    def acquire_or_renew(self) -> bool:
        """Take the lease if it is free, or extend it if we hold it. True while we lead."""
        ttl_ms = self.lease_seconds * 1000
        if self._renew(keys=[LEASE_KEY], args=[self.token, ttl_ms]):
            return True
        return bool(self.redis.set(LEASE_KEY, self.token, nx=True, px=ttl_ms))

    def release(self) -> None:
        if self.redis.get(LEASE_KEY) == self.token.encode():
            self.redis.delete(LEASE_KEY)


def run_due_schedules(now: datetime | None = None, leading: Callable[[], bool] | None = None) -> int:
    """Create jobs for every enabled device on every schedule that is due. Returns jobs created.

    A schedule that was missed (e.g. the orchestrator was down) runs once on
    catch-up, not once per missed slot. ``leading`` is asked before each due
    schedule; once it says no, nothing more is scheduled.
    """
    now = now or timezone.now()
    created = 0
    for schedule in BackupSchedule.objects.filter(enabled=True):
        try:
            due = schedule.next_run() <= now
        except Exception:
            logger.exception('invalid_schedule', extra={'schedule': schedule.pk})
            continue
        if not due:
            continue
        if leading is not None and not leading():
            logger.warning('scheduler_lease_lost', extra={'schedule': schedule.pk})
            break
        with transaction.atomic():
            for device in schedule.devices.filter(enabled=True).select_related(
                'collection_group', 'storage_target', 'credential'
            ):
                try:
                    _, was_created = create_job(device, trigger=BackupJob.TRIGGER_SCHEDULE, schedule=schedule)
                    created += was_created
                except JobError as exc:
                    logger.warning('scheduled_backup_skipped', extra={'device': device.pk, 'reason': str(exc)})
            BackupSchedule.objects.filter(pk=schedule.pk).update(last_run_at=now)
    return created


def prune_sessions(now: datetime) -> bool:
    """Delete expired sessions if the last prune was over an hour ago. True if it ran."""
    global _last_session_prune
    if _last_session_prune is not None and now - _last_session_prune < SESSION_PRUNE_INTERVAL:
        return False
    prune_expired()
    _last_session_prune = now
    return True


def tick(now: datetime | None = None, leading: Callable[[], bool] | None = None) -> None:
    now = now or timezone.now()
    created = run_due_schedules(now, leading)
    expired = expire_stale_jobs(now)
    prune_sessions(now)
    if created or expired:
        logger.info('scheduler_tick', extra={'jobs_created': created, 'jobs_expired': expired})
