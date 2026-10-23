import pytest
from django.contrib.auth.models import User
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


def _client_for(user):
    client = APIClient()
    client.force_authenticate(user)
    return client


def test_staff_can_delete_device(device):
    staff = User.objects.create_user('staff', password='x', is_staff=True)

    resp = _client_for(staff).delete(f'/api/devices/{device.pk}/')

    assert resp.status_code == 204
    assert not Device.objects.filter(pk=device.pk).exists()


def test_user_without_group_access_cannot_delete_device(device):
    user = User.objects.create_user('viewer', password='x')

    resp = _client_for(user).delete(f'/api/devices/{device.pk}/')

    assert resp.status_code == 404
    assert Device.objects.filter(pk=device.pk).exists()


def test_health_needs_no_authentication(db):
    resp = APIClient().get('/api/health/')

    assert resp.status_code == 200
    assert resp.json() == {'status': 'ok'}
