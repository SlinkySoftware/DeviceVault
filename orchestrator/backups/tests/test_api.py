import pytest

from audit.models import AuditLog
from backups.models import BackupJob


@pytest.fixture
def member(setup, make_user, client_for):
    """A client for a user holding ``flags`` on the device's group."""

    def make(*flags):
        user = make_user('-'.join(('member', *flags)), grants={setup['device'].device_group: flags})
        return client_for(user)

    return make


@pytest.fixture
def admin(admin_client):
    return admin_client


def test_backup_now_queues_a_job_once(setup, broker, admin):
    url = f'/api/devices/{setup["device"].id}/backup_now/'

    first = admin.post(url)
    again = admin.post(url)

    assert first.status_code == 202 and first.json()['created']
    assert again.status_code == 200 and not again.json()['created']
    assert again.json()['job']['id'] == first.json()['job']['id']


def test_backup_now_needs_the_group_permission(setup, broker, member):
    url = f'/api/devices/{setup["device"].id}/backup_now/'

    assert member('view').post(url).status_code == 403
    assert member('backup_now').post(url).status_code == 202
    assert AuditLog.objects.filter(action='backup.start', actor_name='member-backup_now').exists()
    assert AuditLog.objects.filter(action='access.denied', actor_name='member-view').exists()


def test_backup_now_explains_misconfigured_devices(setup, broker, admin):
    setup['device'].storage_target = None
    setup['device'].save()

    reply = admin.post(f'/api/devices/{setup["device"].id}/backup_now/')

    assert reply.status_code == 400
    assert 'no storage target' in reply.json()['error']


def test_job_history_needs_view(setup, broker, member, make_user, client_for):
    BackupJob.objects.create(device=setup['device'], storage_target=setup['target'], driver='noop')

    assert client_for(make_user('outsider')).get('/api/backups/').json()['results'] == []
    [job] = member('view').get(f'/api/backups/?device={setup["device"].id}').json()['results']
    assert job['device_name'] == 'Edge 01'


@pytest.fixture
def stored(setup, monkeypatch):
    job = BackupJob.objects.create(
        device=setup['device'], storage_target=setup['target'], driver='noop', state=BackupJob.STORED
    )
    monkeypatch.setattr('backups.api.read_content', lambda j: b'hostname edge-01\n')
    return job


def test_contents_need_view_contents_and_downloads_need_download(stored, member):
    content, download = f'/api/backups/{stored.id}/content/', f'/api/backups/{stored.id}/download/'
    viewer, reader, downloader = member('view'), member('view_contents'), member('download')

    assert viewer.get(content).status_code == 403
    assert viewer.get(download).status_code == 403
    assert reader.get(content).status_code == 200
    assert reader.get(download).status_code == 403
    reply = downloader.get(download)
    assert reply.status_code == 200 and reply['Content-Disposition'].startswith('attachment')

    audited = AuditLog.objects.filter(device_group=stored.device.device_group)
    assert sorted(audited.values_list('action', flat=True)) == ['backup.download', 'backup.view']
    assert audited.get(action='backup.view').details['job'] == str(stored.id)


def test_compare_needs_view_contents_and_one_device(stored, member, setup):
    other = BackupJob.objects.create(
        device=setup['device'], storage_target=setup['target'], driver='noop', state=BackupJob.STORED
    )
    url = f'/api/backups/compare/?a={stored.id}&b={other.id}'

    assert member('view').get(url).status_code == 403
    reply = member('view_contents').get(url)
    assert reply.status_code == 200
    assert reply.json()['a']['content'] == 'hostname edge-01\n'
    assert AuditLog.objects.filter(action='backup.diff').count() == 1


def test_backups_of_hidden_devices_are_not_found(stored, make_user, client_for, setup):
    from devices.models import DeviceGroup

    elsewhere = client_for(make_user('elsewhere', grants={DeviceGroup.objects.create(name='Other'): ['admin']}))

    assert elsewhere.get(f'/api/backups/{stored.id}/').status_code == 404
    assert elsewhere.get(f'/api/backups/{stored.id}/content/').status_code == 404
    assert elsewhere.get(f'/api/devices/{setup["device"].id}/').status_code == 404


def test_content_is_served_as_text(stored, admin):
    reply = admin.get(f'/api/backups/{stored.id}/content/')

    assert reply.status_code == 200
    assert reply.content == b'hostname edge-01\n'
    assert reply['Content-Type'].startswith('text/plain')


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
