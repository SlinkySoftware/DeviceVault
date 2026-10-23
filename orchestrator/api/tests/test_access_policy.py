import pytest
from django.urls import get_resolver
from rest_framework.views import APIView

from credentials.models import Credential, CredentialType
from devices.models import Device, DeviceGroup, DeviceType
from storage.models import StorageTarget

REFERENCE_DATA = [
    '/api/device-types/',
    '/api/manufacturers/',
    '/api/collection-groups/',
    '/api/retention-policies/',
    '/api/backup-schedules/',
    '/api/storage-targets/',
    '/api/credential-types/',
    '/api/device-groups/',
]

ADMINISTRATION = [
    '/api/users/',
    '/api/user-groups/',
    '/api/audit-logs/',
    '/api/workers/',
    '/api/storage-drivers/',
    '/api/flower-endpoints/',
]


@pytest.fixture
def core(db):
    return DeviceGroup.objects.create(name='Core')


@pytest.fixture
def user(make_user, client_for):
    return client_for(make_user('member'))


@pytest.mark.parametrize('path', REFERENCE_DATA)
def test_reference_data_is_readable_but_not_writable_by_users(user, path):
    assert user.get(path).status_code == 200
    assert user.post(path, {'name': 'x'}, format='json').status_code == 403


@pytest.mark.parametrize('path', ADMINISTRATION)
def test_administration_is_for_global_admins(make_user, client_for, admin_client, core, path):
    group_admin = client_for(make_user('group-admin', grants={core: ['admin']}))

    assert group_admin.get(path).status_code == 403
    assert admin_client.get(path).status_code == 200


def test_staff_and_superuser_flags_authorize_nothing(make_user, client_for):
    superuser = client_for(make_user('root', is_staff=True, is_superuser=True))

    assert superuser.get('/api/users/').status_code == 403
    assert superuser.post('/api/device-groups/', {'name': 'Mine'}, format='json').status_code == 403


def test_the_django_admin_site_is_gone(admin_client):
    assert admin_client.get('/admin/').status_code == 404


def test_signed_out_requests_get_401(db):
    from rest_framework.test import APIClient

    assert APIClient().get('/api/devices/').status_code == 401


def test_every_api_view_states_its_permission_classes():
    """CLAUDE.md: never rely on the default permission classes."""
    missing = []

    def walk(patterns, prefix=''):
        for pattern in patterns:
            if hasattr(pattern, 'url_patterns'):
                walk(pattern.url_patterns, prefix + str(pattern.pattern))
                continue
            view = getattr(pattern.callback, 'cls', None)
            if view is None or not issubclass(view, APIView) or view.__name__ == 'APIRootView':
                continue
            actions = getattr(pattern.callback, 'actions', None) or {}
            overrides = [
                getattr(getattr(view, action, None), 'kwargs', {}).get('permission_classes')
                for action in actions.values()
            ]
            if view.permission_classes is APIView.permission_classes and not all(overrides):
                missing.append(prefix + str(pattern.pattern))

    walk(get_resolver().url_patterns)
    assert missing == []


def test_storage_target_settings_are_for_global_admins(user, admin_client):
    StorageTarget.objects.create(name='bucket', driver='s3', config={'bucket': 'b', 'secret_access_key': 'sk'})

    as_user = user.get('/api/storage-targets/').json()[0]
    assert set(as_user) == {'id', 'name', 'description', 'driver'}
    assert admin_client.get('/api/storage-targets/').json()[0]['config']['bucket'] == 'b'


def test_collection_groups_are_a_summary_for_users(user, admin_client):
    from devices.models import CollectionGroup

    CollectionGroup.objects.create(name='DMZ', rabbitmq_queue_id='dmz')

    assert set(user.get('/api/collection-groups/').json()[0]) == {'id', 'name'}
    assert admin_client.get('/api/collection-groups/').json()[0]['rabbitmq_queue_id'] == 'dmz'


def test_ungrouped_devices_are_for_global_admins(db, make_user, client_for, admin_client, core):
    device = Device.objects.create(
        name='loose', ip_address='192.0.2.1', device_type=DeviceType.objects.create(name='Router')
    )
    group_admin = client_for(make_user('group-admin', grants={core: ['admin']}))

    assert group_admin.get(f'/api/devices/{device.id}/').status_code == 404
    assert admin_client.get(f'/api/devices/{device.id}/').status_code == 200


def test_moving_a_device_needs_admin_on_both_groups(db, make_user, client_for, core):
    edge = DeviceGroup.objects.create(name='Edge')
    device = Device.objects.create(
        name='r1', ip_address='192.0.2.1', device_type=DeviceType.objects.create(name='Router'), device_group=core
    )
    one_side = client_for(make_user('one-side', grants={core: ['admin'], edge: ['view']}))
    both = client_for(make_user('both', grants={core: ['admin'], edge: ['admin']}))

    assert one_side.patch(f'/api/devices/{device.id}/', {'device_group': edge.id}, format='json').status_code == 403
    assert both.patch(f'/api/devices/{device.id}/', {'device_group': edge.id}, format='json').status_code == 200


# --- credentials -----------------------------------------------------------------------


@pytest.fixture
def local_type(db):
    return CredentialType.objects.create(name='Local')


def test_credentials_list_global_and_administered_ones(make_user, client_for, core, local_type):
    edge = DeviceGroup.objects.create(name='Edge')
    Credential.objects.create(name='global', credential_type=local_type)
    Credential.objects.create(name='core-only', credential_type=local_type, device_group=core)
    Credential.objects.create(name='edge-only', credential_type=local_type, device_group=edge)
    core_admin = client_for(make_user('core-admin', grants={core: ['admin'], edge: ['download']}))

    names = sorted(row['name'] for row in core_admin.get('/api/credentials/').json())

    assert names == ['core-only', 'global']


def test_credential_secrets_are_write_only_for_everyone(admin_client, local_type):
    created = admin_client.post(
        '/api/credentials/',
        {'name': 'ssh', 'credential_type': local_type.id, 'data': {'username': 'u', 'password': 'hunter2'}},
        format='json',
    )
    assert created.status_code == 201, created.content
    assert 'data' not in created.json() and created.json()['data_keys'] == ['password', 'username']

    # A null value keeps the stored secret.
    pk = created.json()['id']
    admin_client.patch(f'/api/credentials/{pk}/', {'data': {'username': 'v', 'password': None}}, format='json')
    assert Credential.objects.get(pk=pk).data == {'username': 'v', 'password': 'hunter2'}


def test_group_admins_manage_only_their_own_credentials(make_user, client_for, core, local_type):
    client = client_for(make_user('core-admin', grants={core: ['admin']}))
    shared = Credential.objects.create(name='global', credential_type=local_type)
    body = {'name': 'mine', 'credential_type': local_type.id, 'data': {'password': 'p'}}

    assert client.post('/api/credentials/', {**body, 'device_group': None}, format='json').status_code == 403
    assert client.post('/api/credentials/', {**body, 'device_group': core.id}, format='json').status_code == 201
    assert client.patch(f'/api/credentials/{shared.id}/', {'name': 'mine now'}, format='json').status_code == 403
    assert client.delete(f'/api/credentials/{shared.id}/').status_code == 403


def test_devices_use_global_credentials_or_their_groups_own(admin_client, approved_collector, core, local_type):
    approved_collector()
    edge = DeviceGroup.objects.create(name='Edge')
    edge_only = Credential.objects.create(name='edge-only', credential_type=local_type, device_group=edge)
    body = {
        'name': 'r1',
        'ip_address': '192.0.2.1',
        'device_type': DeviceType.objects.create(name='Router').id,
        'device_group': core.id,
        'backup_method': 'noop',
        'credential': edge_only.id,
    }

    refused = admin_client.post('/api/devices/', body, format='json')
    accepted = admin_client.post('/api/devices/', {**body, 'device_group': edge.id}, format='json')

    assert refused.status_code == 400 and 'credential' in refused.json()
    assert accepted.status_code == 201, accepted.content


def test_device_groups_with_devices_or_credentials_cannot_be_deleted(admin_client, core, local_type):
    Credential.objects.create(name='core-only', credential_type=local_type, device_group=core)

    assert admin_client.delete(f'/api/device-groups/{core.id}/').status_code == 409
