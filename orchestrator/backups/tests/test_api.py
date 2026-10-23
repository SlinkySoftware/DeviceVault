import pytest
from django.contrib.auth.models import User
from django.utils import timezone
from rest_framework.test import APIClient

from backups.models import BackupJob
from devices.models import DeviceGroupDjangoPermissions


def client_for(user):
    client = APIClient()
    client.force_authenticate(user)
    return client


def member(setup, *actions):
    user = User.objects.create_user('-'.join(('member', *actions)), password='x')
    link = DeviceGroupDjangoPermissions.ensure_for_group(setup['device'].device_group)
    for action in actions:
        user.user_permissions.add(getattr(link, f'perm_{action}'))
    return client_for(User.objects.get(pk=user.pk))  # fresh permission cache


@pytest.fixture
def admin(db):
    return client_for(User.objects.create_user('admin', password='x', is_staff=True))


def test_backup_now_queues_a_job_once(setup, broker, admin):
    url = f'/api/devices/{setup["device"].id}/backup_now/'

    first = admin.post(url)
    again = admin.post(url)

    assert first.status_code == 202 and first.json()['created']
    assert again.status_code == 200 and not again.json()['created']
    assert again.json()['job']['id'] == first.json()['job']['id']


def test_backup_now_needs_the_group_permission(setup, broker):
    url = f'/api/devices/{setup["device"].id}/backup_now/'

    assert member(setup, 'view').post(url).status_code == 403
    assert member(setup, 'view', 'backup_now').post(url).status_code == 202


def test_backup_now_explains_misconfigured_devices(setup, broker, admin):
    setup['device'].backup_location = None
    setup['device'].save()

    reply = admin.post(f'/api/devices/{setup["device"].id}/backup_now/')

    assert reply.status_code == 400
    assert 'no backup location' in reply.json()['error']


def test_job_history_needs_view_backups(setup, broker):
    BackupJob.objects.create(device=setup['device'], driver='noop')

    assert member(setup, 'view').get('/api/backups/').json()['results'] == []
    [job] = member(setup, 'view_backups').get(f'/api/backups/?device={setup["device"].id}').json()['results']
    assert job['device_name'] == 'Edge 01'


def test_content_is_served_as_a_download(setup, broker, admin, monkeypatch):
    job = BackupJob.objects.create(device=setup['device'], driver='noop', state=BackupJob.STORED)
    monkeypatch.setattr('backups.api.read_content', lambda j: b'hostname edge-01\n')

    reply = admin.get(f'/api/backups/{job.id}/content/')

    assert reply.status_code == 200
    assert reply.content == b'hostname edge-01\n'
    assert reply['Content-Type'].startswith('text/plain')


def test_dashboard_counts_finished_jobs(setup, broker, admin):
    now = timezone.now()
    for state in (BackupJob.STORED, BackupJob.STORED, BackupJob.FAILED, BackupJob.QUEUED):
        BackupJob.objects.create(
            device=setup['device'], driver='noop', state=state, finished_at=None if state == 'queued' else now
        )

    stats = admin.get('/api/dashboard-stats/?days=1').json()

    assert (stats['success24h'], stats['failed24h'], stats['inProgress24h']) == (2, 1, 1)
    assert stats['dailyStats'][-1]['success'] == 2
    assert len(admin.get('/api/recent-backup-activity/?time_filter=24h').json()) == 4


def test_the_file_reading_compare_endpoint_is_gone(admin):
    assert admin.post('/api/backups/compare/', {'a_path': '/etc/passwd', 'b_path': '/etc/passwd'}).status_code in (
        404,
        405,
    )


def test_schedules_validate_cron_and_report_their_next_run(admin):
    bad = admin.post(
        '/api/backup-schedules/',
        {'name': 'x', 'schedule_type': 'custom_cron', 'cron_expression': 'nope'},
        format='json',
    )
    good = admin.post('/api/backup-schedules/', {'name': 'y', 'schedule_type': 'daily', 'hour': 3}, format='json')

    assert bad.status_code == 400 and 'cron_expression' in bad.json()
    assert good.status_code == 201 and good.json()['next_run']
