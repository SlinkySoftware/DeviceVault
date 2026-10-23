import pytest
from django.contrib.auth.models import User
from rest_framework.test import APIClient

from credentials.models import Credential, CredentialType
from devices.models import DeviceGroup, DeviceGroupRole, UserDeviceGroupRole
from locations.models import BackupLocation


def _client(user):
    client = APIClient()
    client.force_authenticate(user)
    return client


@pytest.fixture
def admin(db):
    return _client(User.objects.create_user('admin', password='x', is_staff=True))


@pytest.fixture
def member(db):
    return User.objects.create_user('member', password='x')


@pytest.fixture
def user(member):
    return _client(member)


@pytest.mark.parametrize(
    'path',
    [
        '/api/device-types/',
        '/api/manufacturers/',
        '/api/collection-groups/',
        '/api/retention-policies/',
        '/api/backup-schedules/',
        '/api/backup-locations/',
        '/api/credentials/',
        '/api/credential-types/',
    ],
)
def test_reference_data_is_readable_but_not_writable_by_users(user, path):
    assert user.get(path).status_code == 200
    assert user.post(path, {'name': 'x'}, format='json').status_code == 403


@pytest.mark.parametrize(
    'path',
    [
        '/api/users/',
        '/api/groups/',
        '/api/audit-logs/',
        '/api/device-group-roles/',
        '/api/device-group-permissions/',
        '/api/user-device-group-roles/',
        '/api/group-device-group-roles/',
        '/api/workers/',
    ],
)
def test_administration_endpoints_are_admin_only(user, admin, path):
    assert user.get(path).status_code == 403
    assert admin.get(path).status_code == 200


def test_user_cannot_create_device_group(user):
    assert user.post('/api/device-groups/', {'name': 'Mine'}, format='json').status_code == 403


def test_credential_secrets_are_admin_only(user, admin):
    Credential.objects.create(
        name='core-ssh', credential_type=CredentialType.objects.create(name='Local'), data={'password': 'hunter2'}
    )

    [as_user] = user.get('/api/credentials/').json()
    [as_admin] = admin.get('/api/credentials/').json()

    assert 'data' not in as_user and as_user['name'] == 'core-ssh'
    assert as_admin['data'] == {'password': 'hunter2'}


def test_location_config_is_admin_only(user, admin):
    BackupLocation.objects.create(name='git', location_type='git', config={'url': 'https://u:secret@git'})

    assert 'config' not in user.get('/api/backup-locations/').json()[0]
    assert admin.get('/api/backup-locations/').json()[0]['config']['url'].endswith('@git')


def test_admin_assigns_roles_by_id_and_filters_by_user(admin, member):
    role = DeviceGroupRole.objects.create(
        name='Ops', device_group=DeviceGroup.objects.create(name='Core'), description=''
    )
    other = User.objects.create_user('other', password='x')
    UserDeviceGroupRole.objects.create(user=other, role=role)

    created = admin.post('/api/user-device-group-roles/', {'user': member.id, 'role': role.id}, format='json')
    duplicate = admin.post('/api/user-device-group-roles/', {'user': member.id, 'role': role.id}, format='json')
    listed = admin.get('/api/user-device-group-roles/', {'user': member.id}).json()

    assert created.status_code == 201, created.content
    assert created.json()['role']['name'] == 'Ops'
    assert duplicate.status_code == 400
    assert [a['user'] for a in listed] == [member.id]
