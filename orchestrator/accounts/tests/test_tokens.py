from datetime import timedelta

import pytest
from django.contrib.auth.models import User
from django.urls import get_resolver
from django.utils import timezone
from rest_framework.test import APIClient
from rest_framework.views import APIView

from accounts import tokens
from accounts.models import ApiToken, UserGroup, UserGroupMembership
from audit.models import AuditLog
from core.models import UserProfile
from devices.models import Device, DeviceGroup, DeviceType


@pytest.fixture
def core(db):
    return DeviceGroup.objects.create(name='Core')


@pytest.fixture
def devices(core):
    router = DeviceType.objects.create(name='Router')
    edge = DeviceGroup.objects.create(name='Edge')
    Device.objects.create(name='core-1', ip_address='192.0.2.1', device_type=router, device_group=core)
    Device.objects.create(name='edge-1', ip_address='192.0.2.2', device_type=router, device_group=edge)


@pytest.fixture
def service_account(db):
    def make(username='zabbix', groups=()):
        user = User.objects.create(username=username)
        user.set_unusable_password()
        user.save()
        UserProfile.objects.create(user=user, is_service_account=True)
        for group in groups:
            UserGroupMembership.objects.create(user=user, group=group)
        return user

    return make


# --- authentication ----------------------------------------------------------------------


def test_a_token_acts_as_its_user_within_their_grants(make_user, make_token, token_client, core, devices):
    _, raw = make_token(make_user('member', grants={core: ['view']}))

    names = [row['name'] for row in token_client(raw).get('/api/devices/').json()]

    assert names == ['core-1']


def test_token_requests_need_no_csrf(make_user, make_token, token_client):
    _, raw = make_token(make_user('admin', global_admin=True))

    body = {'username': 'new-user', 'password': 'a-long-password-1'}
    created = token_client(raw).post('/api/users/', body, format='json')

    assert created.status_code == 201, created.content
    assert AuditLog.objects.get(action='user.create').details['token'] == raw.split('_')[1]


@pytest.mark.parametrize('cause', ['unknown', 'revoked', 'expired', 'inactive_user', 'network', 'malformed'])
def test_refused_tokens_all_look_the_same(make_user, make_token, token_client, cause):
    user = make_user('member')
    token, raw = make_token(user, allowed_networks=['198.51.100.0/24'] if cause == 'network' else [])
    if cause == 'unknown':
        raw = raw[:-4] + 'AAAA'
    elif cause == 'revoked':
        ApiToken.objects.filter(pk=token.pk).update(revoked_at=timezone.now())
    elif cause == 'expired':
        ApiToken.objects.filter(pk=token.pk).update(expires_at=timezone.now() - timedelta(seconds=1))
    elif cause == 'inactive_user':
        User.objects.filter(pk=user.pk).update(is_active=False)
    elif cause == 'malformed':
        raw = 'not-a-token'

    answer = token_client(raw).get('/api/devices/')

    assert answer.status_code == 401
    assert answer.json() == {'detail': 'Invalid or expired token.'}
    assert answer['WWW-Authenticate'] == 'Bearer'
    entry = AuditLog.objects.get(action='token.refused')
    assert entry.outcome == AuditLog.DENIED and entry.details['cause'] == cause


def test_refusals_are_audited_once_a_minute_per_address(token_client):
    for _ in range(3):
        token_client('dvt_abcdefgh_nope').get('/api/devices/')
    token_client('dvt_abcdefgh_nope', address='192.0.2.99').get('/api/devices/')

    assert AuditLog.objects.filter(action='token.refused').count() == 2


def test_allowed_networks_admit_their_addresses(make_user, make_token, token_client):
    _, raw = make_token(make_user('member'), allowed_networks=['192.0.2.0/24'])

    assert token_client(raw, address='192.0.2.200').get('/api/devices/').status_code == 200
    assert token_client(raw, address='198.51.100.1').get('/api/devices/').status_code == 401


def test_a_monitoring_token_reaches_no_other_api(make_user, make_token, token_client):
    _, raw = make_token(make_user('member'), scopes=['monitoring'])

    answer = token_client(raw).get('/api/devices/')

    assert answer.status_code == 403


@pytest.mark.parametrize(
    'method, path',
    [
        ('get', '/api/tokens/'),
        ('post', '/api/tokens/'),
        ('get', '/api/admin/tokens/'),
        ('get', '/api/service-accounts/'),
        ('post', '/api/auth/logout/'),
        ('post', '/api/auth/change-password/'),
    ],
)
def test_tokens_cannot_manage_tokens_or_the_session(make_user, make_token, token_client, method, path):
    _, raw = make_token(make_user('admin', global_admin=True))

    answer = getattr(token_client(raw), method)(path, {}, format='json')

    assert answer.status_code in (401, 403)
    assert not ApiToken.objects.exclude(name='test').exists()


def test_tokens_are_rate_limited(settings, make_user, make_token, token_client):
    settings.DEVICEVAULT_API_TOKEN_RATE = '2/min'
    tokens.rate.cache_clear()
    _, raw = make_token(make_user('member'))
    client = token_client(raw)
    try:
        answers = [client.get('/api/devices/').status_code for _ in range(3)]
    finally:
        tokens.rate.cache_clear()

    assert answers == [200, 200, 429]


def test_first_use_from_each_address_is_audited(make_user, make_token, token_client):
    token, raw = make_token(make_user('member'))

    for address in ('192.0.2.10', '192.0.2.10', '192.0.2.11'):
        token_client(raw, address=address).get('/api/devices/')

    uses = AuditLog.objects.filter(action='token.use').order_by('id')
    assert [entry.details['address'] for entry in uses] == ['192.0.2.10', '192.0.2.11']
    token.refresh_from_db()
    assert token.last_used_address == '192.0.2.11' and token.last_used_at is not None


def test_every_view_accepts_known_token_scopes():
    unknown = []

    def walk(patterns, prefix=''):
        for pattern in patterns:
            if hasattr(pattern, 'url_patterns'):
                walk(pattern.url_patterns, prefix + str(pattern.pattern))
                continue
            view = getattr(pattern.callback, 'cls', None)
            if view is not None and issubclass(view, APIView):
                if not set(tokens.view_scopes(view)) <= set(ApiToken.SCOPES):
                    unknown.append(prefix + str(pattern.pattern))

    walk(get_resolver().url_patterns)
    assert unknown == []


# --- a user's own tokens -----------------------------------------------------------------


def test_users_create_list_and_revoke_their_tokens(make_user, client_for, token_client):
    client = client_for(make_user('member'))

    created = client.post('/api/tokens/', {'name': 'ci', 'scopes': ['api'], 'expires_in_days': 30}, format='json')

    assert created.status_code == 201, created.content
    body = created.json()
    assert body['token'].startswith(f'dvt_{body["prefix"]}_') and body['state'] == 'live'
    listed = client.get('/api/tokens/').json()
    assert [row['name'] for row in listed] == ['ci'] and 'token' not in listed[0] and 'digest' not in listed[0]
    assert token_client(body['token']).get('/api/devices/').status_code == 200

    assert client.post(f'/api/tokens/{body["id"]}/revoke/').status_code == 204
    assert token_client(body['token']).get('/api/devices/').status_code == 401
    assert list(AuditLog.objects.filter(action__in=['token.create', 'token.revoke']).values_list('action', flat=True))


def test_only_the_digest_of_the_secret_is_stored(make_user, client_for):
    body = client_for(make_user('member')).post('/api/tokens/', {'name': 'ci', 'scopes': ['api']}, format='json').json()

    token = ApiToken.objects.get(prefix=body['prefix'])
    secret = body['token'].split('_', 2)[2]
    assert token.digest == tokens.digest(secret) and secret not in str(token.__dict__)
    assert token.expires_at - timezone.now() > timedelta(days=89)


@pytest.mark.parametrize(
    'body, field',
    [
        ({'name': 'x', 'scopes': ['api'], 'expires_in_days': 366}, 'expires_in_days'),
        ({'name': 'x', 'scopes': []}, 'scopes'),
        ({'name': 'x', 'scopes': ['root']}, 'scopes'),
        ({'name': 'x', 'scopes': ['monitoring_platform']}, 'scopes'),
        ({'name': 'x', 'scopes': ['api'], 'allowed_networks': ['nowhere']}, 'allowed_networks'),
    ],
)
def test_token_requests_are_validated(make_user, client_for, body, field):
    answer = client_for(make_user('admin', global_admin=True)).post('/api/tokens/', body, format='json')

    assert answer.status_code == 400 and field in answer.json()


def test_token_names_are_unique_among_live_tokens(make_user, client_for):
    client = client_for(make_user('member'))
    first = client.post('/api/tokens/', {'name': 'ci', 'scopes': ['api']}, format='json').json()

    assert client.post('/api/tokens/', {'name': 'ci', 'scopes': ['api']}, format='json').status_code == 400
    client.post(f'/api/tokens/{first["id"]}/revoke/')
    assert client.post('/api/tokens/', {'name': 'ci', 'scopes': ['api']}, format='json').status_code == 201


def test_live_tokens_per_user_are_capped(make_user, make_token, client_for):
    user = make_user('member')
    for n in range(tokens.MAX_LIVE_PER_USER):
        make_token(user, name=f't{n}')

    answer = client_for(user).post('/api/tokens/', {'name': 'one more', 'scopes': ['api']}, format='json')

    assert answer.status_code == 400


def test_users_see_and_revoke_only_their_own_tokens(make_user, make_token, client_for):
    other, _ = make_token(make_user('other'))
    client = client_for(make_user('member'))

    assert client.get('/api/tokens/').json() == []
    assert client.post(f'/api/tokens/{other.pk}/revoke/').status_code == 404


def test_global_admins_list_and_revoke_every_token(make_user, make_token, admin_client, client_for):
    token, _ = make_token(make_user('member'))

    assert [row['prefix'] for row in admin_client.get('/api/admin/tokens/').json()] == [token.prefix]
    assert admin_client.post(f'/api/admin/tokens/{token.pk}/revoke/').status_code == 204
    token.refresh_from_db()
    assert token.revoked_at is not None
    assert client_for(make_user('nobody')).get('/api/admin/tokens/').status_code == 403


# --- service accounts --------------------------------------------------------------------


def test_admins_create_service_accounts_with_tokens(admin_client, core, devices, token_client):
    viewers = UserGroup.objects.create(name='Viewers')
    created = admin_client.post(
        '/api/service-accounts/', {'username': 'zabbix', 'description': 'Zabbix', 'groups': [viewers.id]}, format='json'
    )
    assert created.status_code == 201, created.content
    account = User.objects.get(username='zabbix')
    assert not account.has_usable_password() and account.profile.is_service_account

    issued = admin_client.post(
        f'/api/service-accounts/{account.id}/tokens/', {'name': 'zbx', 'scopes': ['monitoring_platform']}, format='json'
    )

    assert issued.status_code == 201, issued.content
    assert issued.json()['scopes'] == ['monitoring', 'monitoring_platform']
    assert admin_client.get(f'/api/service-accounts/{account.id}/tokens/').json()[0]['name'] == 'zbx'
    assert admin_client.get('/api/service-accounts/').json()[0]['live_tokens'] == 1
    assert AuditLog.objects.filter(action='service_account.create').exists()


def test_service_accounts_never_join_global_admin_groups(admin_client, service_account):
    from accounts.access import administrators_group

    admins = administrators_group()
    plain = UserGroup.objects.create(name='Plain')
    account = service_account(groups=[plain])

    as_member = admin_client.post('/api/service-accounts/', {'username': 'bad', 'groups': [admins.id]}, format='json')
    promoted = admin_client.patch(f'/api/user-groups/{plain.id}/', {'is_global_admin': True}, format='json')

    assert as_member.status_code == 400
    assert promoted.status_code == 400
    assert account.user_groups.get() == plain


def test_service_accounts_are_kept_apart_from_users(admin_client, service_account):
    group = UserGroup.objects.create(name='Monitoring')
    person = User.objects.create_user('person')
    account = service_account(groups=[group])

    assert [row['username'] for row in admin_client.get('/api/users/').json()] == ['admin', 'person']
    assert admin_client.get(f'/api/users/{account.id}/').status_code == 404
    row = admin_client.get(f'/api/user-groups/{group.id}/').json()
    assert row['members'] == [] and row['service_account_names'] == ['zabbix']

    # Saving the group's people leaves its service accounts in place.
    admin_client.patch(f'/api/user-groups/{group.id}/', {'members': [person.id]}, format='json')
    assert sorted(group.members.values_list('username', flat=True)) == ['person', 'zabbix']


def test_service_accounts_cannot_sign_in(service_account):
    account = service_account()
    account.set_password('a-long-password-1')
    account.save()

    client = APIClient(enforce_csrf_checks=False)
    answer = client.post('/api/auth/login/', {'username': 'zabbix', 'password': 'a-long-password-1'}, format='json')

    assert answer.status_code == 400
    assert AuditLog.objects.get(action='auth.login').details['reason'] == 'service_account'


def test_a_service_account_token_outlives_no_person(admin_client, service_account, make_token, token_client):
    account = service_account()
    _, raw = make_token(account)
    assert token_client(raw).get('/api/devices/').status_code == 200

    admin_client.patch(f'/api/service-accounts/{account.id}/', {'is_active': False}, format='json')

    assert token_client(raw).get('/api/devices/').status_code == 401


def test_service_accounts_are_for_global_admins(make_user, client_for, core):
    group_admin = client_for(make_user('group-admin', grants={core: ['admin']}))

    assert group_admin.get('/api/service-accounts/').status_code == 403
