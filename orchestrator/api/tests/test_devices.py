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
