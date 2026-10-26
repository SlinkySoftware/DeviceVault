from datetime import UTC, datetime, timedelta

import pytest

from backups.freshness import INTERVAL_RUNS, device_freshness, expected_interval, stale_factor
from backups.models import BackupJob
from devices.models import Device
from policies.models import BackupSchedule

# A Monday.
NOW = datetime(2026, 10, 26, 12, 0, tzinfo=UTC)


@pytest.fixture(autouse=True)
def utc(settings):
    settings.DEVICEVAULT_DISPLAY_TIMEZONE = 'UTC'
    settings.DEVICEVAULT_STALE_FACTOR = 1.5


def schedule(**fields):
    return BackupSchedule.objects.create(name=fields.pop('name', 'S'), **fields)


def device(setup, name, *, created=NOW - timedelta(days=30), **fields):
    base = setup['device']
    made = Device.objects.create(
        name=name,
        ip_address=f'192.0.2.{Device.objects.count() + 20}',
        device_type=base.device_type,
        device_group=base.device_group,
        collection_group=base.collection_group,
        storage_target=base.storage_target,
        backup_method=fields.pop('backup_method', 'noop'),
        **fields,
    )
    Device.objects.filter(pk=made.pk).update(created_at=created)
    return made


def job(dev, state, finished_at):
    return BackupJob.objects.create(
        device=dev, state=state, driver='noop', storage_target=dev.storage_target, finished_at=finished_at
    )


@pytest.mark.parametrize(
    ('fields', 'interval'),
    [
        ({'schedule_type': 'daily', 'hour': 2}, timedelta(days=1)),
        ({'schedule_type': 'weekly', 'hour': 2, 'day_of_week': '0'}, timedelta(days=7)),
        ({'schedule_type': 'custom_cron', 'cron_expression': '0 */6 * * *'}, timedelta(hours=6)),
        ({'schedule_type': 'custom_cron', 'cron_expression': '*/15 * * * *'}, timedelta(minutes=15)),
    ],
)
def test_expected_interval_is_the_gap_between_runs(db, fields, interval):
    assert expected_interval(schedule(**fields), NOW) == interval


def test_an_uneven_schedule_uses_its_longest_gap(db):
    # Weekdays only: Friday to Monday is the longest wait, whatever day it is now.
    weekdays = schedule(schedule_type='custom_cron', cron_expression='0 2 * * 1-5')

    assert expected_interval(weekdays, NOW) == timedelta(days=3)


def test_no_or_a_disabled_schedule_has_no_interval(db):
    assert expected_interval(None, NOW) is None
    assert expected_interval(schedule(enabled=False), NOW) is None


def test_stale_factor_comes_from_settings(settings):
    settings.DEVICEVAULT_STALE_FACTOR = 2.0

    assert stale_factor() == 2.0


def test_a_daily_device_is_overdue_after_one_and_a_half_days_without_a_stored_backup(setup):
    daily = schedule(schedule_type='daily', hour=2)
    fresh = device(setup, 'fresh', schedule=daily)
    job(fresh, BackupJob.STORED, NOW - timedelta(hours=20))
    stale = device(setup, 'stale', schedule=daily)
    job(stale, BackupJob.STORED, NOW - timedelta(hours=40))
    job(stale, BackupJob.FAILED, NOW - timedelta(hours=1))  # failures do not count

    result = device_freshness(Device.objects.all(), NOW)

    assert result[fresh.pk].expected_interval == timedelta(days=1)
    assert result[fresh.pk].last_success == NOW - timedelta(hours=20)
    assert result[fresh.pk].next_due_at == NOW + timedelta(hours=16)
    assert result[fresh.pk].overdue is False
    assert result[stale.pk].last_success == NOW - timedelta(hours=40)
    assert result[stale.pk].next_due_at == NOW - timedelta(hours=4)
    assert result[stale.pk].overdue is True


def test_the_latest_stored_job_counts_not_the_device_status(setup):
    daily = schedule(schedule_type='daily', hour=2)
    dev = device(setup, 'edge', schedule=daily, last_backup_status='success', last_backup_time=NOW)
    job(dev, BackupJob.STORED, NOW - timedelta(days=3))
    job(dev, BackupJob.STORED, NOW - timedelta(days=5))
    job(dev, BackupJob.TIMED_OUT, NOW)

    assert device_freshness(Device.objects.filter(pk=dev.pk), NOW)[dev.pk].last_success == NOW - timedelta(days=3)


def test_a_weekly_device_has_a_week_and_a_half(setup):
    weekly = schedule(schedule_type='weekly', hour=2, day_of_week='0')
    dev = device(setup, 'edge', schedule=weekly)
    job(dev, BackupJob.STORED, NOW - timedelta(days=9))

    info = device_freshness(Device.objects.filter(pk=dev.pk), NOW)[dev.pk]

    assert info.expected_interval == timedelta(days=7)
    assert info.overdue is False
    assert info.next_due_at == NOW + timedelta(days=1, hours=12)


def test_a_cron_schedule_uses_its_own_interval(setup):
    six_hourly = schedule(schedule_type='custom_cron', cron_expression='0 */6 * * *')
    dev = device(setup, 'edge', schedule=six_hourly)
    job(dev, BackupJob.STORED, NOW - timedelta(hours=10))

    info = device_freshness(Device.objects.filter(pk=dev.pk), NOW)[dev.pk]

    assert info.expected_interval == timedelta(hours=6) and info.overdue is True


def test_a_device_never_backed_up_is_overdue_once_older_than_the_allowance(setup):
    daily = schedule(schedule_type='daily', hour=2)
    new = device(setup, 'new', schedule=daily, created=NOW - timedelta(hours=12))
    old = device(setup, 'old', schedule=daily, created=NOW - timedelta(days=2))

    result = device_freshness(Device.objects.all(), NOW)

    assert result[new.pk].last_success is None
    assert result[new.pk].next_due_at == NOW + timedelta(hours=24)
    assert result[new.pk].overdue is False
    assert result[old.pk].overdue is True


def test_disabled_and_inactive_devices_are_never_overdue(setup):
    daily = schedule(schedule_type='daily', hour=2)
    disabled = device(setup, 'disabled', schedule=daily, enabled=False)
    inactive = device(setup, 'inactive', schedule=daily, inactive_at=NOW - timedelta(days=10))

    result = device_freshness(Device.objects.all(), NOW)

    for dev in (disabled, inactive):
        assert result[dev.pk].expected_interval == timedelta(days=1)
        assert result[dev.pk].overdue is False


def test_devices_without_an_enabled_schedule_have_no_interval(setup):
    off = schedule(schedule_type='daily', hour=2, enabled=False)
    manual = device(setup, 'manual')
    paused = device(setup, 'paused', schedule=off)
    push_only = device(setup, 'push-only', schedule=schedule(schedule_type='daily'), backup_method='', push_mode='scp')
    job(push_only, BackupJob.STORED, NOW - timedelta(days=30))

    result = device_freshness(Device.objects.all(), NOW)

    for dev in (manual, paused, push_only):
        assert (result[dev.pk].expected_interval, result[dev.pk].next_due_at, result[dev.pk].overdue) == (
            None,
            None,
            None,
        )
    assert result[push_only.pk].last_success == NOW - timedelta(days=30)


def test_the_factor_widens_the_allowance(setup, settings):
    settings.DEVICEVAULT_STALE_FACTOR = 3.0
    dev = device(setup, 'edge', schedule=schedule(schedule_type='daily', hour=2))
    job(dev, BackupJob.STORED, NOW - timedelta(hours=60))

    assert device_freshness(Device.objects.filter(pk=dev.pk), NOW)[dev.pk].overdue is False


def test_many_devices_take_two_queries_and_one_interval_per_schedule(setup, django_assert_num_queries, monkeypatch):
    schedules = [schedule(name=f'S{i}', schedule_type='daily', hour=i) for i in range(3)]
    for i in range(30):
        dev = device(setup, f'd{i}', schedule=schedules[i % 3])
        job(dev, BackupJob.STORED, NOW - timedelta(hours=i))
    calls = []
    original = BackupSchedule.next_run_after

    def counted(self, moment):
        calls.append(self.pk)
        return original(self, moment)

    monkeypatch.setattr(BackupSchedule, 'next_run_after', counted)

    with django_assert_num_queries(2):
        result = device_freshness(Device.objects.all(), NOW)

    assert len(result) == Device.objects.count()
    assert sorted(calls) == sorted([s.pk for s in schedules] * (INTERVAL_RUNS + 1))
