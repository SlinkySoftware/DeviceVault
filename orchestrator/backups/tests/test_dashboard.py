from datetime import timedelta

import pytest
from django.utils import timezone

from backups.models import BackupJob
from core.timezone_utils import local_now
from devices.models import Device, DeviceGroup


@pytest.fixture
def admin(admin_client):
    return admin_client


@pytest.fixture
def job(setup):
    """Make a job of ``device`` that finished ``ago`` before now, having taken ``took``."""

    def make(state=BackupJob.STORED, *, ago=timedelta(0), took=timedelta(seconds=10), device=None, **fields):
        finished = None if state in BackupJob.ACTIVE_STATES else timezone.now() - ago
        made = BackupJob.objects.create(
            device=device or setup['device'],
            storage_target=setup['target'],
            driver='noop',
            state=state,
            finished_at=finished,
            **fields,
        )
        if finished:
            BackupJob.objects.filter(pk=made.pk).update(created_at=finished - took)
        return made

    return make


@pytest.fixture
def other_device(setup):
    return Device.objects.create(
        name='Branch 02',
        device_type=setup['device'].device_type,
        ip_address='192.0.2.20',
        device_group=DeviceGroup.objects.create(name='Branches'),
        collection_group=setup['group'],
        storage_target=setup['target'],
        backup_method='noop',
    )


@pytest.fixture
def core_viewer(setup, make_user, client_for):
    return client_for(make_user('core-viewer', grants={setup['device'].device_group: ['view']}))


def test_summary_counts_the_last_day(job, admin):
    for state in (BackupJob.STORED, BackupJob.STORED, BackupJob.FAILED, BackupJob.QUEUED):
        job(state)
    job(ago=timedelta(days=2))

    summary = admin.get('/api/dashboard/summary/').json()

    assert (summary['stored_24h'], summary['failed_24h'], summary['in_progress']) == (2, 1, 1)
    assert summary['avg_duration_s'] == 10.0
    assert summary['devices_by_type'] == [{'name': 'Router', 'icon': 'router', 'count': 1}]


def test_activity_lists_recent_jobs(job, admin):
    job()
    job(BackupJob.QUEUED)

    assert len(admin.get('/api/dashboard/activity/?window=24h').json()) == 2


def test_trend_has_every_day_with_rates_durations_and_changes(job, admin):
    job(took=timedelta(seconds=10), changed=True, collect_duration_ms=4000)
    job(took=timedelta(seconds=30), changed=False, collect_duration_ms=6000)
    job(BackupJob.FAILED)
    job(BackupJob.TIMED_OUT, ago=timedelta(days=2))
    job(ago=timedelta(days=40))  # outside the period

    days = admin.get('/api/dashboard/trend/?days=7').json()['days']

    assert len(days) == 7 and days[-1]['date'] == local_now().date().isoformat()
    today = days[-1]
    assert (today['stored'], today['failed'], today['changed']) == (2, 1, 1)
    assert today['rate'] == pytest.approx(66.7)
    assert (today['avg_duration_s'], today['max_duration_s'], today['avg_collect_s']) == (20.0, 30.0, 5.0)
    assert days[-3]['failed'] == 1 and days[-3]['rate'] == 0
    assert days[0] == {
        'date': days[0]['date'],
        'stored': 0,
        'failed': 0,
        'rate': None,
        'changed': 0,
        'avg_duration_s': None,
        'max_duration_s': None,
        'avg_collect_s': None,
    }
    assert sum(day['stored'] for day in admin.get('/api/dashboard/trend/?days=90').json()['days']) == 3


@pytest.mark.parametrize('path', ['trend', 'failing', 'storage', 'push-refusals'])
def test_periods_are_fixed(admin, path):
    reply = admin.get(f'/api/dashboard/{path}/?days=8')

    assert reply.status_code == 400
    assert '7, 14, 30, 90' in reply.json()['error']


def test_trend_uses_the_display_time_zone(job, admin, settings):
    settings.DEVICEVAULT_DISPLAY_TIMEZONE = 'Pacific/Kiritimati'  # UTC+14, so its day differs from UTC's
    job()

    days = admin.get('/api/dashboard/trend/?days=7').json()['days']

    assert days[-1]['date'] == local_now().date().isoformat() and days[-1]['stored'] == 1


def test_freshness_reports_the_stalest_device_per_group(setup, job, other_device, admin):
    job(ago=timedelta(days=3))
    job(BackupJob.FAILED)  # a failure does not make it fresh
    fresh = Device.objects.create(
        name='Edge 03',
        device_type=setup['device'].device_type,
        ip_address='192.0.2.11',
        device_group=setup['device'].device_group,
        collection_group=setup['group'],
        storage_target=setup['target'],
        backup_method='noop',
    )
    job(device=fresh, ago=timedelta(hours=1))
    Device.objects.create(
        name='Off',
        ip_address='192.0.2.12',
        device_type=setup['device'].device_type,
        device_group=setup['device'].device_group,
        enabled=False,
    )

    rows = admin.get('/api/dashboard/freshness/').json()

    # Never backed up is staler than any backup.
    assert [row['device_group_name'] for row in rows] == ['Branches', 'Core']
    branches, core = rows
    assert (branches['devices'], branches['never']) == (1, 1)
    assert branches['stalest'] == {'id': other_device.pk, 'name': 'Branch 02', 'last_success': None}
    assert (core['devices'], core['never'], core['older_24h'], core['older_7d']) == (2, 0, 1, 0)
    assert core['stalest']['name'] == 'Edge 01'


def test_failing_ranks_devices_by_failures(setup, job, other_device, admin):
    for _ in range(3):
        job(BackupJob.FAILED, error='x' * 500, ago=timedelta(hours=2))
    job(ago=timedelta(hours=1))
    job(BackupJob.TIMED_OUT, device=other_device, error='timed out')
    job(BackupJob.FAILED, device=other_device, ago=timedelta(days=60))  # outside the period

    rows = admin.get('/api/dashboard/failing/?days=7').json()

    assert [(row['device_name'], row['failed']) for row in rows] == [('Edge 01', 3), ('Branch 02', 1)]
    edge, branch = rows
    assert edge['recovered'] and edge['stored'] == 1 and len(edge['error']) == 200
    assert not branch['recovered'] and branch['last_success'] is None and branch['error'] == 'timed out'
    assert len(admin.get('/api/dashboard/failing/?days=7&limit=1').json()) == 1


def test_storage_sums_what_targets_hold(job, admin):
    job(size_bytes=1000, ago=timedelta(days=60))
    job(size_bytes=500)
    job(size_bytes=9999, pruned_at=timezone.now())
    job(BackupJob.FAILED)

    [row] = admin.get('/api/dashboard/storage/?days=30').json()

    assert (row['name'], row['driver'], row['backups'], row['size_bytes']) == ('Local', 'filesystem', 2, 1500)
    assert (row['added_backups'], row['added_bytes']) == (1, 500)


def test_cards_cover_only_visible_devices(job, other_device, core_viewer):
    job(BackupJob.FAILED, device=other_device, size_bytes=10)
    job(BackupJob.FAILED)

    assert core_viewer.get('/api/dashboard/summary/').json()['failed_24h'] == 1
    assert sum(day['failed'] for day in core_viewer.get('/api/dashboard/trend/?days=7').json()['days']) == 1
    assert [row['device_name'] for row in core_viewer.get('/api/dashboard/failing/').json()] == ['Edge 01']
    assert [row['device_group_name'] for row in core_viewer.get('/api/dashboard/freshness/').json()] == ['Core']
    assert core_viewer.get('/api/dashboard/storage/').json() == []
    assert len(core_viewer.get('/api/dashboard/activity/?window=24h').json()) == 1


def test_push_refusals_are_for_global_admins(setup, admin, core_viewer):
    from core.models import Worker
    from push.models import PushRejection

    worker = Worker.objects.get(name='collector-1')
    now = timezone.now()
    for ip, reason, ago in [
        ('198.51.100.1', 'unknown_source', 0),
        ('198.51.100.1', 'auth_failed', 1),
        ('198.51.100.2', 'unknown_source', 2),
        ('198.51.100.3', 'unknown_source', 24 * 40),  # outside the period
    ]:
        PushRejection.objects.create(
            worker=worker, at=now - timedelta(hours=ago), source_ip=ip, protocol='ssh', reason=reason
        )

    assert core_viewer.get('/api/dashboard/push-refusals/').status_code == 403
    body = admin.get('/api/dashboard/push-refusals/?days=7').json()
    assert sum(day['count'] for day in body['days']) == 3
    assert body['by_reason'] == [{'reason': 'unknown_source', 'count': 2}, {'reason': 'auth_failed', 'count': 1}]
    top = body['sources'][0]
    assert (top['source_ip'], top['count'], top['last_reason'], top['receiver']) == (
        '198.51.100.1',
        2,
        'unknown_source',
        'collector-1',
    )
