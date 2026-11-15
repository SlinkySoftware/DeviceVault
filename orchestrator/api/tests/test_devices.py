import pytest
from rest_framework.test import APIClient

from devices.models import Device, DeviceGroup, DeviceType


@pytest.fixture
def device(db):
    return Device.objects.create(
        name='edge-01',
        ip_address='192.0.2.10',
        device_type=DeviceType.objects.create(name='Router'),
        device_group=DeviceGroup.objects.create(name='Core'),
    )


def test_global_admin_can_delete_device(device, admin_client):
    resp = admin_client.delete(f'/api/devices/{device.pk}/')

    assert resp.status_code == 204
    assert not Device.objects.filter(pk=device.pk).exists()


def test_user_without_group_access_cannot_delete_device(device, make_user, client_for):
    resp = client_for(make_user('viewer')).delete(f'/api/devices/{device.pk}/')

    assert resp.status_code == 404
    assert Device.objects.filter(pk=device.pk).exists()


def test_health_needs_no_authentication(db):
    resp = APIClient().get('/api/health/')

    assert resp.status_code == 200
    assert resp.json() == {'status': 'ok'}


def test_version_needs_no_authentication(db):
    from devicevault_protocol.version import version

    resp = APIClient().get('/api/version/')

    assert resp.status_code == 200
    assert resp.json() == {'version': version()}


HOST_KEY = 'ssh-ed25519 AAAAC3NzaC1lZDI1NTE5AAAAIJ/5z9AzdT8Dm9DM5cwhVsGr+7YDGjr3iqkJqscQWMlL'


def test_a_device_shows_its_pinned_host_key_as_a_fingerprint(device, admin_client):
    assert admin_client.get(f'/api/devices/{device.pk}/').json()['ssh_host_key_fingerprint'] == ''
    Device.objects.filter(pk=device.pk).update(ssh_host_key=HOST_KEY)

    body = admin_client.get(f'/api/devices/{device.pk}/').json()

    assert body['ssh_host_key_type'] == 'ssh-ed25519'
    assert body['ssh_host_key_fingerprint'] == 'SHA256:kuehv88oMZA/RgHRswCgnfGgnwqVeQ91l54enX5Lzec'
    assert 'ssh_host_key' not in body


def test_the_host_key_cannot_be_set_through_the_api(device, admin_client):
    reply = admin_client.patch(f'/api/devices/{device.pk}/', {'ssh_host_key': HOST_KEY}, format='json')

    assert reply.status_code == 200
    assert Device.objects.get(pk=device.pk).ssh_host_key == ''


def test_group_admins_forget_a_host_key_and_it_is_audited(device, make_user, client_for):
    from audit.models import AuditLog

    Device.objects.filter(pk=device.pk).update(ssh_host_key=HOST_KEY)
    viewer = client_for(make_user('viewer', grants={device.device_group: ['view', 'backup_now']}))
    admin = client_for(make_user('groupadmin', grants={device.device_group: ['admin']}))

    assert viewer.post(f'/api/devices/{device.pk}/forget_host_key/').status_code == 403
    assert Device.objects.get(pk=device.pk).ssh_host_key == HOST_KEY

    reply = admin.post(f'/api/devices/{device.pk}/forget_host_key/')

    assert reply.status_code == 200 and reply.json()['ssh_host_key_fingerprint'] == ''
    device.refresh_from_db()
    assert device.ssh_host_key == '' and device.ssh_host_key_pinned_at is None
    entry = AuditLog.objects.get(action='device.host_key_forget')
    assert entry.actor_name == 'groupadmin' and entry.details['key_type'] == 'ssh-ed25519'
