"""How fresh each device's backups are, judged by its own schedule.

A scheduled device has an expected interval: the gap between its schedule's
next two runs. It is overdue once its latest successful backup (the newest
``stored`` job) is older than that interval times ``DV_STALE_FACTOR``; a device
never backed up is overdue once it is itself that old. Disabled and inactive
devices are never overdue. Devices with no enabled schedule (push-only or
manual) have no interval, so ``overdue`` is None for them.
"""

from dataclasses import dataclass
from datetime import datetime, timedelta

from django.conf import settings
from django.db.models import Max, Q, QuerySet
from django.utils import timezone

from backups.models import BackupJob
from policies.models import BackupSchedule


@dataclass(frozen=True)
class Freshness:
    """One device's freshness at a moment."""

    # Gap between the schedule's next two runs; None without an enabled schedule.
    expected_interval: timedelta | None
    # When the newest stored backup finished; None if never backed up.
    last_success: datetime | None
    # The deadline for a successful backup: the last success (or, never backed up, the device's
    # creation) plus expected_interval x stale_factor(). None without an interval.
    next_due_at: datetime | None
    # Past next_due_at, for an enabled, active device; always False for disabled or inactive
    # ones; None without an interval.
    overdue: bool | None


def stale_factor() -> float:
    """How many expected intervals a device may go without a successful backup (``DV_STALE_FACTOR``)."""
    return float(settings.DEVICEVAULT_STALE_FACTOR)


def expected_interval(schedule: BackupSchedule | None, now: datetime | None = None) -> timedelta | None:
    """The gap between ``schedule``'s next two runs after ``now``; None for no schedule or a disabled one."""
    if schedule is None or not schedule.enabled:
        return None
    first = schedule.next_run_after(now or timezone.now())
    return schedule.next_run_after(first) - first


def device_freshness(devices: QuerySet, now: datetime | None = None) -> dict[int, Freshness]:
    """Freshness of every device in ``devices``, keyed by device id.

    One query for the devices with their latest successful backup, one for their
    schedules; each schedule's interval is worked out once.
    """
    now = now or timezone.now()
    rows = list(
        devices.order_by()
        .annotate(last_success=Max('backup_jobs__finished_at', filter=Q(backup_jobs__state=BackupJob.STORED)))
        .values_list('pk', 'schedule_id', 'backup_method', 'enabled', 'inactive_at', 'created_at', 'last_success')
    )
    schedule_ids = {row[1] for row in rows if row[1] is not None}
    intervals = {
        schedule.pk: expected_interval(schedule, now) for schedule in BackupSchedule.objects.filter(pk__in=schedule_ids)
    }
    factor = stale_factor()

    result = {}
    for pk, schedule_id, backup_method, enabled, inactive_at, created_at, last_success in rows:
        # A device that is not polled is never backed up by its schedule.
        interval = intervals.get(schedule_id) if backup_method else None
        if interval is None:
            result[pk] = Freshness(None, last_success, None, None)
            continue
        due = (last_success or created_at) + interval * factor
        active = enabled and inactive_at is None
        result[pk] = Freshness(interval, last_success, due, active and now > due)
    return result
