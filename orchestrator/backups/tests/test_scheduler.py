from datetime import UTC, datetime, timedelta

import pytest

from backups.models import BackupJob
from backups.scheduler import run_due_schedules
from policies.models import BackupSchedule


def test_schedules_fire_in_the_display_timezone(nightly):
    assert nightly.next_run() == datetime(2026, 10, 22, 15, 0, tzinfo=UTC)


def test_due_schedules_queue_one_job_per_device_and_catch_up_once(nightly, broker):
    assert run_due_schedules(datetime(2026, 10, 22, 14, 59, tzinfo=UTC)) == 0

    # Two days late: one catch-up run, not one per missed night.
    late = datetime(2026, 10, 24, 15, 30, tzinfo=UTC)
    assert run_due_schedules(late) == 1
    assert run_due_schedules(late + timedelta(minutes=1)) == 0

    job = BackupJob.objects.get()
    assert (job.trigger, job.schedule) == (BackupJob.TRIGGER_SCHEDULE, nightly)
    nightly.refresh_from_db()
    assert nightly.last_run_at == late


def test_disabled_devices_and_schedules_are_skipped(nightly, broker, setup):
    setup['device'].enabled = False
    setup['device'].save()
    assert run_due_schedules(datetime(2026, 10, 23, 0, 0, tzinfo=UTC)) == 0

    nightly.enabled = False
    nightly.save()
    assert nightly.next_run() is None


@pytest.mark.parametrize(
    ('fields', 'cron'),
    [
        ({'schedule_type': 'weekly', 'day_of_week': '1'}, '0 2 * * 1'),
        ({'schedule_type': 'monthly', 'day_of_month': 31}, '0 2 L * *'),
        ({'schedule_type': 'custom_cron', 'cron_expression': ' */15 * * * * '}, '*/15 * * * *'),
    ],
)
def test_schedule_types_map_to_cron(fields, cron):
    assert BackupSchedule(hour=2, minute=0, **fields).cron() == cron
