"""User groups, their grants and the dependency rules between permission flags."""

import pytest
from django.db import IntegrityError, transaction

from accounts import access
from accounts.models import DeviceGroupGrant, UserGroup, UserGroupMembership
from audit.models import AuditLog
from devices.models import DeviceGroup


@pytest.fixture
def core(db):
    return DeviceGroup.objects.create(name='Core')


@pytest.fixture
def operators(db):
    return UserGroup.objects.create(name='Operators')


@pytest.mark.parametrize(
    'flags',
    [
        {'view': False},
        {'download': True},
        {'admin': True},
        {'admin': True, 'backup_now': True, 'view_contents': True},
    ],
)
def test_the_database_refuses_grants_that_break_the_dependency_rules(core, operators, flags):
    with pytest.raises(IntegrityError), transaction.atomic():
        DeviceGroupGrant.objects.create(user_group=operators, device_group=core, **flags)


def test_one_grant_per_user_group_and_device_group(core, operators):
    DeviceGroupGrant.objects.create(user_group=operators, device_group=core)
    with pytest.raises(IntegrityError), transaction.atomic():
        DeviceGroupGrant.objects.create(user_group=operators, device_group=core, backup_now=True)


def grant(device_group, **flags):
    return {'device_group': device_group.id, **flags}


def test_saving_admin_ticks_every_other_flag(admin_client, core):
    reply = admin_client.post(
        '/api/user-groups/', {'name': 'Core admins', 'grants': [grant(core, admin=True)]}, format='json'
    )

    assert reply.status_code == 201, reply.content
    [row] = reply.json()['grants']
    assert row == {
        'device_group': core.id,
        'device_group_name': 'Core',
        'view': True,
        'backup_now': True,
        'view_contents': True,
        'download': True,
        'admin': True,
    }


@pytest.mark.parametrize(
    ('flags', 'message'),
    [
        ({'view': False}, 'includes view'),
        ({'download': True}, 'download needs view_contents'),
        ({'view': False, 'backup_now': True}, 'includes view'),
    ],
)
def test_the_api_refuses_grants_that_break_the_dependency_rules(admin_client, core, flags, message):
    reply = admin_client.post('/api/user-groups/', {'name': 'X', 'grants': [grant(core, **flags)]}, format='json')

    assert reply.status_code == 400
    assert message in str(reply.json())


def test_a_device_group_appears_once_per_user_group(admin_client, core):
    reply = admin_client.post('/api/user-groups/', {'name': 'X', 'grants': [grant(core), grant(core)]}, format='json')

    assert reply.status_code == 400


def test_group_edits_replace_members_and_grants_and_are_audited(admin_client, make_user, core, operators):
    alice, bob = make_user('alice'), make_user('bob')
    UserGroupMembership.objects.create(user=alice, group=operators)

    reply = admin_client.patch(
        f'/api/user-groups/{operators.id}/',
        {'members': [bob.id], 'grants': [grant(core, backup_now=True)]},
        format='json',
    )

    assert reply.status_code == 200, reply.content
    assert reply.json()['member_names'] == ['bob']
    assert access.flags_on(bob, core) == ['view', 'backup_now']
    assert access.grants_for(alice) == {}
    entry = AuditLog.objects.get(action='user_group.update')
    assert entry.details['before']['members'] == ['alice']
    assert entry.details['after'] == {
        'name': 'Operators',
        'is_global_admin': False,
        'members': ['bob'],
        'grants': {'Core': ['view', 'backup_now']},
    }


def test_membership_changes_apply_on_the_next_request(make_user, client_for, admin_client, core, operators):
    DeviceGroupGrant.objects.create(user_group=operators, device_group=core)
    user = make_user('carol')
    client = client_for(user)
    assert client.get(f'/api/device-groups/{core.id}/').status_code == 404

    admin_client.patch(f'/api/user-groups/{operators.id}/', {'members': [user.id]}, format='json')

    assert client.get(f'/api/device-groups/{core.id}/').status_code == 200


def test_global_admins_hold_everything(make_user, core):
    admin = make_user('root', global_admin=True)

    assert access.can(admin, 'admin', core)
    assert access.can(admin, 'download', None)
    assert access.grants_for(admin) == {core.id: access.ALL_FLAGS}


def test_inactive_users_hold_nothing(make_user, core):
    user = make_user('gone', global_admin=True, grants={core: ['admin']}, is_active=False)

    assert not access.is_global_admin(user)
    assert access.grants_for(user) == {}


# --- the last global administrator ------------------------------------------------------


@pytest.fixture
def root(make_user):
    return make_user('root', global_admin=True)


@pytest.fixture
def root_client(root, client_for):
    return client_for(root)


def test_the_administrators_group_cannot_be_deleted_or_lose_its_flag(root_client):
    group = access.administrators_group()

    assert root_client.delete(f'/api/user-groups/{group.id}/').status_code == 400
    assert (
        root_client.patch(f'/api/user-groups/{group.id}/', {'is_global_admin': False}, format='json').status_code == 400
    )
    assert UserGroup.objects.filter(pk=group.pk, is_global_admin=True).exists()


def test_the_last_global_admin_cannot_be_removed(root, root_client, make_user):
    other = make_user('other')
    group = access.administrators_group()

    assert root_client.patch(f'/api/user-groups/{group.id}/', {'members': []}, format='json').status_code == 400
    assert root_client.patch(f'/api/users/{root.id}/', {'groups': []}, format='json').status_code == 400
    assert access.active_global_admins().get() == root

    # With a second administrator, the first may go.
    root_client.patch(f'/api/user-groups/{group.id}/', {'members': [root.id, other.id]}, format='json')
    assert root_client.patch(f'/api/users/{root.id}/', {'groups': []}, format='json').status_code == 200


def test_the_last_global_admin_group_cannot_lose_its_flag(make_user, client_for):
    custom = UserGroup.objects.create(name='Root', is_global_admin=True)
    user = make_user('solo')
    UserGroupMembership.objects.create(user=user, group=custom)
    client = client_for(user)

    assert client.patch(f'/api/user-groups/{custom.id}/', {'is_global_admin': False}, format='json').status_code == 400
    assert client.delete(f'/api/user-groups/{custom.id}/').status_code == 400


def test_users_cannot_disable_or_delete_themselves(root, root_client, make_user):
    make_user('backup-admin', global_admin=True)

    assert root_client.patch(f'/api/users/{root.id}/', {'is_active': False}, format='json').status_code == 400
    assert root_client.delete(f'/api/users/{root.id}/').status_code == 400


def test_external_group_memberships_are_read_only(admin_client, make_user):
    external = UserGroup.objects.create(name='idp:ops', source=UserGroup.EXTERNAL)

    reply = admin_client.patch(f'/api/user-groups/{external.id}/', {'members': [make_user('x').id]}, format='json')

    assert reply.status_code == 400
