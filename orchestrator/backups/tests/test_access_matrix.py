"""Every role against every device and backup endpoint, and the union of a user's grants."""

import pytest

from backups.models import BackupJob

FLAG_SETS = {
    'none': None,
    'view': ['view'],
    'backup_now': ['backup_now'],
    'view_contents': ['view_contents'],
    'download': ['download'],
    'admin': ['admin'],
    'global': 'global',
}

# Expected status per role: (list devices count, retrieve device, backup now, content, download, patch device)
EXPECTED = {
    'none': (0, 404, 404, 404, 404, 404),
    'view': (1, 200, 403, 403, 403, 403),
    'backup_now': (1, 200, 202, 403, 403, 403),
    'view_contents': (1, 200, 403, 200, 403, 403),
    'download': (1, 200, 403, 200, 200, 403),
    'admin': (1, 200, 202, 200, 200, 200),
    'global': (1, 200, 202, 200, 200, 200),
}


@pytest.fixture
def estate(setup, broker, monkeypatch):
    monkeypatch.setattr('backups.api.read_content', lambda job: b'hostname edge-01\n')
    job = BackupJob.objects.create(
        device=setup['device'], storage_target=setup['target'], driver='noop', state=BackupJob.STORED
    )
    return setup['device'], job


@pytest.mark.parametrize('role', list(FLAG_SETS))
def test_role_endpoint_matrix(role, estate, make_user, client_for):
    device, job = estate
    flags = FLAG_SETS[role]
    if flags == 'global':
        user = make_user(role, global_admin=True)
    else:
        user = make_user(role, grants={device.device_group: flags} if flags else None)
    client = client_for(user)

    listed = len(client.get('/api/devices/').json())
    statuses = (
        client.get(f'/api/devices/{device.id}/').status_code,
        client.post(f'/api/devices/{device.id}/backup_now/').status_code,
        client.get(f'/api/backups/{job.id}/content/').status_code,
        client.get(f'/api/backups/{job.id}/download/').status_code,
        client.patch(f'/api/devices/{device.id}/', {'enabled': False}, format='json').status_code,
    )

    assert (listed, *statuses) == EXPECTED[role]


def test_grants_are_the_union_of_a_users_groups(estate, make_user, client_for):
    from accounts.models import DeviceGroupGrant, UserGroup, UserGroupMembership

    device, job = estate
    user = make_user('both', grants={device.device_group: ['backup_now']})
    readers = UserGroup.objects.create(name='Readers')
    DeviceGroupGrant.objects.create(user_group=readers, device_group=device.device_group, view_contents=True)
    UserGroupMembership.objects.create(user=user, group=readers)
    client = client_for(user)

    assert client.post(f'/api/devices/{device.id}/backup_now/').status_code == 202
    assert client.get(f'/api/backups/{job.id}/content/').status_code == 200
    assert client.get(f'/api/backups/{job.id}/download/').status_code == 403
    assert client.get('/api/auth/user/').json()['grants'] == {
        str(device.device_group_id): ['view', 'backup_now', 'view_contents']
    }
