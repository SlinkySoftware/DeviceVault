"""The scheduler: runs due backup schedules and expires stuck jobs.

Every orchestrator node may run it; only the holder of a Redis lease acts, so
with two nodes one schedules and the other takes over within ``LEASE_SECONDS``
if it stops.
"""

import logging
import uuid
from datetime import datetime

from django.db import transaction
from django.utils import timezone
from redis import Redis

from backups.jobs import JobError, create_job, expire_stale_jobs
from backups.models import BackupJob
from policies.models import BackupSchedule

logger = logging.getLogger('devicevault.scheduler')

LEASE_KEY = 'dv:scheduler:leader'
LEASE_SECONDS = 60

# Extend the lease only if we still hold it (compare-and-extend).
_RENEW = """
if redis.call('get', KEYS[1]) == ARGV[1] then
    return redis.call('pexpire', KEYS[1], ARGV[2])
end
return 0
"""


class Leadership:
    def __init__(self, redis: Redis, node: str | None = None):
        self.redis = redis
        self.token = f'{node or "node"}:{uuid.uuid4().hex}'
        self._renew = redis.register_script(_RENEW)

    def acquire_or_renew(self) -> bool:
        ttl_ms = LEASE_SECONDS * 1000
        if self._renew(keys=[LEASE_KEY], args=[self.token, ttl_ms]):
            return True
        return bool(self.redis.set(LEASE_KEY, self.token, nx=True, px=ttl_ms))

    def release(self) -> None:
        if self.redis.get(LEASE_KEY) == self.token.encode():
            self.redis.delete(LEASE_KEY)


def run_due_schedules(now: datetime | None = None) -> int:
    """Create jobs for every enabled device on every schedule that is due. Returns jobs created.

    A schedule that was missed (e.g. the orchestrator was down) runs once on
    catch-up, not once per missed slot.
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


def tick(now: datetime | None = None) -> None:
    now = now or timezone.now()
    created = run_due_schedules(now)
    expired = expire_stale_jobs(now)
    if created or expired:
        logger.info('scheduler_tick', extra={'jobs_created': created, 'jobs_expired': expired})
