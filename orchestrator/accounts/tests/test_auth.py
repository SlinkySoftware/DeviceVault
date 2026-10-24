"""Signing in and out: sessions, CSRF, timeouts, throttling, users and the bootstrap admin."""

import time

import pytest
from django.conf import settings
from django.core.management import call_command
from rest_framework.test import APIClient

from accounts import access, sessions
from audit.models import AuditLog

PASSWORD = 'correct horse battery staple'


@pytest.fixture
def alice(make_user):
    return make_user('alice', password=PASSWORD)


def sign_in(client, username='alice', password=PASSWORD):
    return client.post('/api/auth/login/', {'username': username, 'password': password}, format='json')


def test_signing_in_starts_a_session_and_reports_the_user(alice):
    client = APIClient()

    reply = sign_in(client)

    assert reply.status_code == 200
    assert reply.json()['user']['username'] == 'alice'
    cookie = reply.cookies[settings.SESSION_COOKIE_NAME]
    assert cookie['httponly'] is True and cookie['samesite'] == 'Lax'
    me = client.get('/api/auth/user/').json()
    assert (me['is_global_admin'], me['grants'], me['source']) == (False, {}, 'local')
    assert AuditLog.objects.get(action='auth.login').actor == alice


def test_wrong_passwords_and_unknown_users_get_the_same_answer(alice):
    wrong = sign_in(APIClient(), password='nope')
    unknown = sign_in(APIClient(), username='mallory')

    assert wrong.status_code == unknown.status_code == 400
    assert wrong.json() == unknown.json() == {'detail': 'Invalid username or password.'}
    failures = AuditLog.objects.filter(action='auth.login', outcome=AuditLog.FAILURE)
    assert sorted(failures.values_list('actor_name', flat=True)) == ['alice', 'mallory']


def test_signing_out_ends_the_session(alice):
    client = APIClient()
    sign_in(client)

    assert client.post('/api/auth/logout/').status_code == 204
    assert client.get('/api/auth/user/').status_code == 401
    assert AuditLog.objects.filter(action='auth.logout', actor=alice).exists()


def test_csrf_is_enforced_on_sign_in_and_unsafe_requests(alice):
    client = APIClient(enforce_csrf_checks=True)

    assert sign_in(client).status_code == 403
    client.get('/api/auth/csrf/')
    token = client.cookies[settings.CSRF_COOKIE_NAME].value
    assert (
        client.post(
            '/api/auth/login/', {'username': 'alice', 'password': PASSWORD}, format='json', HTTP_X_CSRFTOKEN=token
        ).status_code
        == 200
    )

    # Signing in rotates the token.
    token = client.cookies[settings.CSRF_COOKIE_NAME].value
    assert client.post('/api/auth/logout/').status_code == 403
    assert client.get('/api/auth/user/').status_code == 200
    assert client.post('/api/auth/logout/', HTTP_X_CSRFTOKEN=token).status_code == 204


@pytest.mark.parametrize(
    ('stamp', 'reason'),
    [(sessions.SEEN_AT, 'idle'), (sessions.LOGIN_AT, 'lifetime')],
)
def test_timed_out_sessions_end(alice, stamp, reason):
    client = APIClient()
    sign_in(client)
    session = client.session
    session[stamp] = int(time.time()) - settings.DEVICEVAULT_SESSION_MAX_HOURS * 3600 - 1
    session.save()

    assert client.get('/api/auth/user/').status_code == 401
    assert AuditLog.objects.get(action='auth.session_expired').details == {'reason': reason}


def test_use_keeps_a_session_alive(alice):
    client = APIClient()
    sign_in(client)
    session = client.session
    session[sessions.SEEN_AT] = int(time.time()) - sessions.TOUCH_SECONDS - 5
    session.save()

    assert client.get('/api/auth/user/').status_code == 200
    assert time.time() - client.session[sessions.SEEN_AT] < 5


def test_repeated_failures_lock_the_username_out(alice, settings):
    settings.DEVICEVAULT_LOGIN_MAX_FAILURES = 3
    for _ in range(3):
        sign_in(APIClient(REMOTE_ADDR='192.0.2.1'), password='nope')

    # The right password from another address is refused too, without being checked.
    locked = sign_in(APIClient(REMOTE_ADDR='192.0.2.2'))

    assert locked.status_code == 429
    assert AuditLog.objects.filter(details__reason='locked_out').count() == 1


def test_repeated_failures_lock_the_address_out(alice, settings):
    settings.DEVICEVAULT_LOGIN_MAX_FAILURES = 3
    for name in ('a', 'b', 'c'):
        sign_in(APIClient(REMOTE_ADDR='192.0.2.9'), username=name)

    assert sign_in(APIClient(REMOTE_ADDR='192.0.2.9')).status_code == 429
    assert sign_in(APIClient(REMOTE_ADDR='192.0.2.10')).status_code == 200


def test_a_successful_sign_in_resets_the_username_count(alice, settings):
    settings.DEVICEVAULT_LOGIN_MAX_FAILURES = 2
    sign_in(APIClient(REMOTE_ADDR='192.0.2.1'), password='nope')
    assert sign_in(APIClient(REMOTE_ADDR='192.0.2.2')).status_code == 200
    sign_in(APIClient(REMOTE_ADDR='192.0.2.3'), password='nope')

    assert sign_in(APIClient(REMOTE_ADDR='192.0.2.4')).status_code == 200


def test_the_client_address_comes_from_the_proxy_hop(alice):
    sign_in(APIClient(REMOTE_ADDR='10.0.0.2', HTTP_X_FORWARDED_FOR='198.51.100.7, 203.0.113.5'))

    assert AuditLog.objects.get(action='auth.login').ip == '203.0.113.5'


def test_disabled_users_cannot_sign_in_and_lose_their_session(alice, admin_client):
    client = APIClient()
    sign_in(client)

    admin_client.patch(f'/api/users/{alice.id}/', {'is_active': False}, format='json')

    assert client.get('/api/auth/user/').status_code == 401
    assert sign_in(APIClient()).status_code == 400


def test_changing_your_password_keeps_your_session_and_validates(alice):
    client = APIClient()
    sign_in(client)

    weak = client.post('/api/auth/change-password/', {'current_password': PASSWORD, 'new_password': '123'})
    good = client.post(
        '/api/auth/change-password/', {'current_password': PASSWORD, 'new_password': 'a much better passphrase'}
    )

    assert weak.status_code == 400 and 'new_password' in weak.json()
    assert good.status_code == 204
    assert client.get('/api/auth/user/').status_code == 200


# --- user administration -----------------------------------------------------------------


def test_admins_create_local_users_with_groups(admin_client):
    operators = access.administrators_group()

    weak = admin_client.post('/api/users/', {'username': 'bob', 'password': 'bob'}, format='json')
    good = admin_client.post(
        '/api/users/', {'username': 'bob', 'password': PASSWORD, 'groups': [operators.id]}, format='json'
    )

    assert weak.status_code == 400 and 'password' in weak.json()
    assert good.status_code == 201, good.content
    assert 'password' not in good.json()
    assert (good.json()['groups'], good.json()['is_global_admin'], good.json()['source']) == (
        [operators.id],
        True,
        'local',
    )
    assert AuditLog.objects.get(action='user.create').details['after']['groups'] == ['Administrators']


def test_admins_reset_passwords(admin_client, alice):
    reply = admin_client.post(f'/api/users/{alice.id}/set_password/', {'password': 'a fresh passphrase'})

    assert reply.status_code == 204
    alice.refresh_from_db()
    assert alice.check_password('a fresh passphrase')


def test_usernames_cannot_change(admin_client, alice):
    assert admin_client.patch(f'/api/users/{alice.id}/', {'username': 'eve'}, format='json').status_code == 400


# --- bootstrap -----------------------------------------------------------------------------


def test_create_admin_makes_a_global_admin_once(db, monkeypatch):
    monkeypatch.setenv('DV_ADMIN_USERNAME', 'boot')
    monkeypatch.setenv('DV_ADMIN_PASSWORD', PASSWORD)

    call_command('create_admin')
    call_command('create_admin')

    [admin] = access.active_global_admins()
    assert admin.username == 'boot'
    assert not (admin.is_staff or admin.is_superuser)
    assert access.administrators_group().is_builtin


def test_create_admin_restores_the_bootstrap_user_when_no_admin_is_left(make_user, monkeypatch):
    monkeypatch.setenv('DV_ADMIN_USERNAME', 'boot')
    boot = make_user('boot', is_active=False)
    other = make_user('other', global_admin=True)

    call_command('create_admin')
    assert not access.is_global_admin(boot)

    other.delete()
    call_command('create_admin')
    boot.refresh_from_db()
    assert boot.is_active and access.is_global_admin(boot)
