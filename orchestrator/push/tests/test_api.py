import pytest

from audit.models import AuditLog
from devicevault_protocol import signing
from push.api import authorized_key_errors
from push.models import PushRejection
from push.service import settings_for

# A real OpenSSH ed25519 public key (from `ssh-keygen -t ed25519`).
ED25519 = 'ssh-ed25519 AAAAC3NzaC1lZDI1NTE5AAAAIBTRDIemsIFAdQeYJbzUhavBWiqHm4lI0EFJPpwSuCvU edge@example'


def url(worker, action='receiver'):
    return f'/api/workers/{worker.pk}/{action}/'


def test_receiver_settings_round_trip_with_a_write_only_password(receiver, admin_client, published):
    _, worker = receiver
    before = len(published)

    resp = admin_client.patch(
        url(worker),
        {'ssh_enabled': True, 'ssh_port': 2022, 'ssh_username': 'dev', 'ssh_password': 's3cret', 'max_file_size': 4096},
        format='json',
    )

    assert resp.status_code == 200, resp.content
    body = admin_client.get(url(worker)).json()
    assert 'ssh_password' not in body and body['ssh_password_set'] is True
    assert (body['ssh_port'], body['ssh_username'], body['max_file_size']) == (2022, 'dev', 4096)
    assert settings_for(worker).ssh_password == 's3cret'
    assert len(published) == before + 1  # the receiver got a new assignment
    entry = AuditLog.objects.get(action='receiver.update')
    assert 's3cret' not in str(entry.details) and entry.details['password_changed'] is True

    # Omitting the password keeps it; an empty one removes it.
    admin_client.patch(url(worker), {'ssh_enabled': True, 'ssh_username': 'dev'}, format='json')
    assert settings_for(worker).ssh_password == 's3cret'
    resp = admin_client.patch(url(worker), {'ssh_enabled': False, 'ssh_password': ''}, format='json')
    assert resp.status_code == 200 and settings_for(worker).ssh_password == ''


def test_ssh_needs_a_password_or_keys(receiver, admin_client):
    _, worker = receiver

    resp = admin_client.patch(url(worker), {'ssh_enabled': True}, format='json')
    assert resp.status_code == 400 and 'ssh_password' in resp.json()

    resp = admin_client.patch(url(worker), {'ssh_enabled': True, 'ssh_authorized_keys': ED25519}, format='json')
    assert resp.status_code == 200, resp.content


@pytest.mark.parametrize(
    ('text', 'error'),
    [
        (ED25519, None),
        (f'# devices\n\n{ED25519}\n', None),
        ('from="10.0.0.1" ' + ED25519, 'supported key type'),
        ('ssh-ed25519 not*base64', 'base64'),
        ('ssh-rsa ' + ED25519.split()[1], 'does not match'),
    ],
)
def test_authorized_keys_are_checked(text, error):
    errors = authorized_key_errors(text)
    assert (error is None and errors == []) or any(error in e for e in errors)


def test_receiver_endpoints_are_for_receivers_and_admins(receiver, approved_collector, make_user, client_for):
    _, worker = receiver
    collector = approved_collector()
    admin = client_for(make_user('root', global_admin=True))
    user = client_for(make_user('someone'))

    assert admin.get(url(collector)).status_code == 404
    assert admin.get(url(collector, 'rejections')).status_code == 404
    assert user.get(url(worker)).status_code == 403
    assert user.get(url(worker, 'rejections')).status_code == 403


def test_rejections_are_listed_newest_first(receiver, admin_client):
    from django.utils import timezone

    _, worker = receiver
    for n in range(3):
        PushRejection.objects.create(
            worker=worker, at=timezone.now(), source_ip=f'198.51.100.{n}', protocol='ssh', reason='auth_failed'
        )

    rows = admin_client.get(url(worker, 'rejections')).json()

    assert [row['source_ip'] for row in rows] == ['198.51.100.2', '198.51.100.1', '198.51.100.0']


def test_a_receiver_can_only_be_approved_as_one(worker_keys, admin_client):
    from core import workers
    from push.tests.conftest import RECEIVER_CAPABILITIES

    keys = worker_keys('receiver-2')
    pending = workers.handle_event(keys.event(drivers=(), storage=(), capabilities=RECEIVER_CAPABILITIES))
    collector = workers.handle_event(worker_keys('collector-9').event())

    assert admin_client.post(url(pending, 'approve'), {'role': 'collector'}, format='json').status_code == 400
    assert admin_client.post(url(collector, 'approve'), {'role': 'receiver'}, format='json').status_code == 400
    resp = admin_client.post(url(pending, 'approve'), {'role': 'receiver'}, format='json')
    assert resp.status_code == 200, resp.content
    assert settings_for(pending).ssh_enabled is False  # listens for nothing until configured
    assert signing.fingerprint(pending.signing_key) == resp.json()['fingerprint']


# --- devices --------------------------------------------------------------------------------


def device_payload(setup, **overrides):
    device = setup['device']
    return {
        'name': 'edge-02',
        'ip_address': '192.0.2.20',
        'device_type': device.device_type_id,
        'device_group': device.device_group_id,
        'collection_group': device.collection_group_id,
        'storage_target': device.storage_target_id,
        'backup_method': 'noop',
        **overrides,
    }


def test_device_push_settings(setup, admin_client):
    post = lambda **kw: admin_client.post('/api/devices/', device_payload(setup, **kw), format='json')  # noqa: E731

    resp = post(push_mode='ssh', push_filename_pattern='*-confg', backup_method='')
    assert resp.status_code == 201, resp.content
    assert (resp.json()['push_mode'], resp.json()['backup_method']) == ('ssh', '')

    assert 'backup_method' in post(ip_address='192.0.2.21', backup_method='').json()
    assert 'storage_target' in post(ip_address='192.0.2.22', push_mode='ssh', storage_target=None).json()
    assert 'ip_address' in post(ip_address='192.0.2.10').json()  # the fixture device's address
    assert 'ip_address' in post(ip_address='::ffff:192.0.2.10').json()  # the same address


def test_push_only_devices_cannot_be_polled(setup, receiver):
    from backups.jobs import JobError, create_job

    setup['device'].backup_method = ''
    setup['device'].push_mode = 'ssh'
    with pytest.raises(JobError, match='not polled'):
        create_job(setup['device'])
