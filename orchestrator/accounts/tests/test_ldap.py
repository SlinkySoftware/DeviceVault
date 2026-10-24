"""LDAP sign-in against a fake directory: search and bind, linking, provisioning, group sync, providers API."""

import uuid

import ldap
import pytest
from django.contrib.auth.models import User
from ldap.filter import escape_filter_chars
from rest_framework.test import APIClient

from accounts import access
from accounts.models import AuthProvider, ExternalIdentity, GroupMappingRule, UserGroup, UserGroupMembership
from accounts.providers.ldap import IN_CHAIN
from audit.models import AuditLog
from core.models import UserProfile

USER_FILTER = '(&(objectClass=person)(uid={username}))'
BASE = 'ou=people,dc=example,dc=com'


class FakeDirectory:
    """Just enough of a python-ldap connection: binds, and searches by the filters DeviceVault builds."""

    def __init__(self):
        self.users = {}  # dn -> (password, attrs)
        self.groups = {}  # name -> member dns
        self.filters = []
        self.binds = []
        self.down = set()
        self.service = ('cn=svc,dc=example,dc=com', 'svc-secret')

    def add_user(self, uid, password, *, groups=(), mail='', entry_uuid=None, **attrs):
        dn = f'uid={uid},{BASE}'
        values = {
            'uid': [uid.encode()],
            'mail': [mail.encode()] if mail else [],
            'givenName': [attrs.get('first', uid.title()).encode()],
            'sn': [b'Tester'],
            'entryUUID': [(entry_uuid or str(uuid.uuid4())).encode()],
            'memberOf': [f'cn={g},ou=groups,dc=example,dc=com'.encode() for g in groups],
        }
        self.users[dn] = (password, values)
        for group in groups:
            self.groups.setdefault(group, set()).add(dn)
        return dn

    def initialize(self, uri):
        directory = self

        class Connection:
            def set_option(self, option, value):
                pass

            def start_tls_s(self):
                pass

            def simple_bind_s(self, who, cred):
                if uri in directory.down:
                    raise ldap.SERVER_DOWN({'desc': "Can't contact LDAP server"})
                directory.binds.append((uri, who))
                if (who, cred) == directory.service:
                    return
                if who in directory.users and directory.users[who][0] == cred and cred:
                    return
                raise ldap.INVALID_CREDENTIALS({'desc': 'Invalid credentials'})

            def search_ext_s(self, base, scope, query, attrlist=None, timeout=-1, sizelimit=0):
                directory.filters.append(query)
                found = []
                for dn, (_, attrs) in directory.users.items():
                    uid = attrs['uid'][0].decode()
                    if query == USER_FILTER.replace('{username}', escape_filter_chars(uid)):
                        found.append((dn, attrs))
                for name, members in directory.groups.items():
                    for member in members:
                        escaped = escape_filter_chars(member)
                        if query in (f'(member={escaped})', f'(member:{IN_CHAIN}:={escaped})'):
                            found.append((f'cn={name},ou=groups,dc=example,dc=com', {'cn': [name.encode()]}))
                return found

            def unbind_s(self):
                pass

        return Connection()


@pytest.fixture
def directory(monkeypatch):
    fake = FakeDirectory()
    monkeypatch.setattr('accounts.providers.ldap.ldap.initialize', fake.initialize)
    return fake


def ldap_config(**overrides):
    return {
        'server_uris': ['ldaps://dc1.example.com', 'ldaps://dc2.example.com'],
        'bind_dn': 'cn=svc,dc=example,dc=com',
        'bind_password': 'svc-secret',
        'user_base_dn': BASE,
        'user_filter': USER_FILTER,
        **overrides,
    }


@pytest.fixture
def provider(db):
    return AuthProvider.objects.create(slug='corp', name='Corp LDAP', kind='ldap', config=ldap_config())


@pytest.fixture
def operators(db):
    return UserGroup.objects.create(name='Operators')


def sign_in(username, password, **client_kwargs):
    return APIClient(**client_kwargs).post(
        '/api/auth/login/', {'username': username, 'password': password}, format='json'
    )


def test_first_sign_in_creates_a_linked_user_with_mapped_groups(directory, provider, operators):
    GroupMappingRule.objects.create(provider=provider, external_group='NetOps', user_group=operators)
    directory.add_user('carol', 'pw1', groups=['netops', 'Staff'], mail='carol@example.com', entry_uuid='u-1')

    reply = sign_in('carol', 'pw1')

    assert reply.status_code == 200, reply.content
    user = User.objects.get(username='carol')
    assert not user.has_usable_password()
    assert user.email == 'carol@example.com' and user.first_name == 'Carol'
    assert ExternalIdentity.objects.get(user=user).subject == 'u-1'
    # Group names match case-insensitively for LDAP; unmapped groups are ignored.
    assert [m.group.name for m in user.group_memberships.all()] == ['Operators']
    assert reply.json()['user']['source'] == 'external'
    entry = AuditLog.objects.get(action='auth.login', outcome='success')
    assert entry.details['provider'] == 'corp' and entry.details['groups_added'] == ['Operators']


def test_the_password_is_checked_by_binding_as_the_user(directory, provider):
    dn = directory.add_user('carol', 'pw1')

    assert sign_in('carol', 'wrong').status_code == 400
    assert ('ldaps://dc1.example.com', dn) in directory.binds
    assert not User.objects.filter(username='carol').exists()


def test_an_empty_password_never_reaches_the_directory(directory, provider):
    directory.add_user('carol', '')

    assert sign_in('carol', '').status_code == 400
    assert directory.binds == []


def test_usernames_are_escaped_into_the_filter(directory, provider):
    directory.add_user('carol', 'pw1')

    assert sign_in('*)(uid=*', 'pw1').status_code == 400
    assert directory.filters[-1] == '(&(objectClass=person)(uid=\\2a\\29\\28uid=\\2a))'


def test_servers_are_tried_in_order(directory, provider):
    directory.add_user('carol', 'pw1')
    directory.down.add('ldaps://dc1.example.com')

    assert sign_in('carol', 'pw1').status_code == 200
    assert directory.binds[0][0] == 'ldaps://dc2.example.com'


def test_an_unreachable_directory_is_a_failed_sign_in(directory, provider):
    directory.down.update(provider.config['server_uris'])

    assert sign_in('carol', 'pw1').status_code == 400
    assert AuditLog.objects.get(action='auth.login').details['unavailable'] == ['corp']


def test_identities_link_on_subject_never_on_username_or_email(directory, provider, make_user):
    local = make_user('carol', email='carol@example.com')
    directory.add_user('carol', 'pw1', mail='carol@example.com', entry_uuid='u-1')

    assert sign_in('carol', 'pw1').status_code == 200

    linked = ExternalIdentity.objects.get(subject='u-1').user
    assert linked != local and linked.username == 'carol-2'
    local.refresh_from_db()
    assert local.has_usable_password()

    # The same subject keeps signing in as the same user, whatever its username becomes.
    directory.users[next(iter(directory.users))][1]['mail'] = [b'new@example.com']
    sign_in('carol', 'pw1')
    linked.refresh_from_db()
    assert linked.email == 'new@example.com'
    assert User.objects.count() == 2


def test_group_sync_adds_and_removes_only_provider_memberships(directory, provider, operators):
    auditors = UserGroup.objects.create(name='Auditors')
    GroupMappingRule.objects.create(provider=provider, external_group='netops', user_group=operators)
    GroupMappingRule.objects.create(provider=provider, external_group='audit', user_group=auditors)
    dn = directory.add_user('carol', 'pw1', groups=['netops'])
    sign_in('carol', 'pw1')
    user = User.objects.get(username='carol')
    manual = UserGroup.objects.create(name='Hand picked')
    UserGroupMembership.objects.create(user=user, group=manual)

    directory.groups = {'audit': {dn}}
    directory.users[dn][1]['memberOf'] = [b'cn=audit,ou=groups,dc=example,dc=com']
    sign_in('carol', 'pw1')

    assert sorted(user.user_groups.values_list('name', flat=True)) == ['Auditors', 'Hand picked']
    assert AuditLog.objects.filter(action='auth.login').first().details['groups_removed'] == ['Operators']


def test_unmapped_groups_become_external_groups_when_asked(directory, provider):
    provider.auto_create_groups = True
    provider.save()
    directory.add_user('carol', 'pw1', groups=['netops'])

    sign_in('carol', 'pw1')

    group = UserGroup.objects.get(provider=provider)
    assert (group.name, group.source, group.external_id) == ('corp:netops', 'external', 'netops')
    assert not group.grants.exists()
    assert User.objects.get(username='carol').user_groups.get() == group


def test_login_group_and_provisioning_rules_refuse_users(directory, provider):
    directory.add_user('carol', 'pw1', groups=['staff'])
    provider.login_group = 'DeviceVault Users'
    provider.save()

    refused = sign_in('carol', 'pw1')
    assert refused.status_code == 403
    assert AuditLog.objects.get(action='auth.login').details['reason'] == 'not_in_login_group'

    provider.login_group = 'staff'
    provider.auto_create_users = False
    provider.save()
    assert sign_in('carol', 'pw1').status_code == 403
    assert not User.objects.filter(username='carol').exists()


def test_disabled_external_users_cannot_sign_in(directory, provider):
    directory.add_user('carol', 'pw1')
    sign_in('carol', 'pw1')
    User.objects.filter(username='carol').update(is_active=False)

    assert sign_in('carol', 'pw1').status_code == 403


def test_nested_groups_use_the_in_chain_rule(directory, provider):
    provider.config = ldap_config(group_source='search', nested_groups=True)
    provider.save()
    directory.add_user('carol', 'pw1', groups=['netops'])
    provider.auto_create_groups = True
    provider.save()

    sign_in('carol', 'pw1')

    assert any(IN_CHAIN in query for query in directory.filters)
    assert UserGroup.objects.filter(external_id='netops').exists()


def test_object_guids_are_read_as_uuids():
    from accounts.providers.ldap import _identity

    guid = uuid.UUID('12345678-1234-5678-1234-567812345678')

    assert _identity('objectGUID', [guid.bytes_le]) == str(guid)
    assert _identity('entryUUID', [b'abc']) == 'abc'


# --- local sign-in when local authentication is off -----------------------------------------


def test_only_break_glass_users_sign_in_locally_when_local_auth_is_off(make_user, settings):
    settings.DEVICEVAULT_LOCAL_AUTH_ENABLED = False
    make_user('plain', password='pw-plain')
    glass = make_user('glass', password='pw-glass')
    UserProfile.objects.create(user=glass, break_glass=True)

    assert sign_in('plain', 'pw-plain').status_code == 400
    assert sign_in('glass', 'pw-glass').status_code == 200
    assert AuditLog.objects.filter(details__reason='local_auth_disabled').count() == 1


def test_admins_toggle_break_glass_for_local_users_only(admin_client, make_user, directory, provider):
    local = make_user('local')
    directory.add_user('carol', 'pw1')
    sign_in('carol', 'pw1')
    external = User.objects.get(username='carol')

    on = admin_client.patch(f'/api/users/{local.id}/', {'break_glass': True}, format='json')
    refused = admin_client.patch(f'/api/users/{external.id}/', {'break_glass': True}, format='json')

    assert on.status_code == 200 and on.json()['break_glass'] is True
    assert refused.status_code == 400
    assert admin_client.post(f'/api/users/{external.id}/set_password/', {'password': 'x' * 20}).status_code == 400


# --- the providers API ------------------------------------------------------------------------


def test_provider_secrets_are_write_only_and_kept_when_left_empty(admin_client):
    created = admin_client.post(
        '/api/auth-providers/', {'slug': 'ad', 'name': 'AD', 'kind': 'ldap', 'config': ldap_config()}, format='json'
    )
    assert created.status_code == 201, created.content
    body = created.json()
    assert body['config']['bind_password'] is None and body['secrets_set'] == ['bind_password']

    admin_client.patch(
        f'/api/auth-providers/{body["id"]}/', {'config': ldap_config(bind_password=None, order=1)}, format='json'
    )
    provider = AuthProvider.objects.get(slug='ad')
    assert provider.config['bind_password'] == 'svc-secret'
    assert 'svc-secret' not in str(AuditLog.objects.filter(action__startswith='provider.').values_list('details'))


def test_provider_config_is_validated_against_the_kind(admin_client):
    bad = admin_client.post(
        '/api/auth-providers/',
        {'slug': 'ad', 'name': 'AD', 'kind': 'ldap', 'config': ldap_config(user_filter='(uid=x)', server_uris=['x'])},
        format='json',
    )

    assert bad.status_code == 400
    errors = ' '.join(bad.json()['config'])
    assert '{username}' in errors and 'ldap://' in errors


def test_provider_slug_and_kind_are_fixed(admin_client, provider):
    reply = admin_client.patch(f'/api/auth-providers/{provider.id}/', {'slug': 'other'}, format='json')

    assert reply.status_code == 400


def test_the_test_action_reports_the_directory_view_of_a_user(admin_client, directory, provider):
    directory.add_user('carol', 'pw1', groups=['netops'])

    found = admin_client.post(f'/api/auth-providers/{provider.id}/test/', {'username': 'carol'}, format='json').json()
    directory.down.update(provider.config['server_uris'])
    down = admin_client.post(f'/api/auth-providers/{provider.id}/test/', {}, format='json').json()

    assert found['ok'] and found['user']['groups'] == ['netops'] and found['server'] == 'ldaps://dc1.example.com'
    assert not down['ok'] and "Can't contact" in down['error']


def test_kinds_publish_their_settings_schema(admin_client):
    kinds = {kind['key']: kind for kind in admin_client.get('/api/auth-provider-kinds/').json()}
    kind = kinds['ldap']

    assert kind['key'] == 'ldap' and kind['password_login']
    assert kind['params_schema']['properties']['bind_password']['anyOf'][0]['writeOnly'] is True


def test_deleting_a_provider_removes_what_it_added(admin_client, directory, provider, operators):
    GroupMappingRule.objects.create(provider=provider, external_group='netops', user_group=operators)
    directory.add_user('carol', 'pw1', groups=['netops'])
    sign_in('carol', 'pw1')
    carol = User.objects.get(username='carol')

    assert admin_client.delete(f'/api/auth-providers/{provider.id}/').status_code == 204

    assert not carol.group_memberships.exists() and not carol.external_identities.exists()
    assert UserGroup.objects.filter(pk=operators.pk).exists()


def test_the_login_page_lists_enabled_providers(provider):
    AuthProvider.objects.create(slug='off', name='Off', kind='ldap', enabled=False, config=ldap_config())

    config = APIClient().get('/api/auth/config/').json()

    assert config['providers'] == [{'slug': 'corp', 'name': 'Corp LDAP', 'kind': 'ldap', 'password_login': True}]


def test_create_admin_makes_a_break_glass_user(db, monkeypatch):
    from django.core.management import call_command

    monkeypatch.setenv('DV_ADMIN_USERNAME', 'boot')
    monkeypatch.setenv('DV_ADMIN_PASSWORD', 'correct horse battery staple')

    call_command('create_admin')

    boot = User.objects.get(username='boot')
    assert UserProfile.objects.get(user=boot).break_glass
    assert access.is_global_admin(boot)


def test_create_admin_flags_an_existing_bootstrap_user_when_no_break_glass_user_exists(make_user, monkeypatch):
    from django.core.management import call_command

    monkeypatch.setenv('DV_ADMIN_USERNAME', 'boot')
    boot = make_user('boot', global_admin=True)

    call_command('create_admin')

    assert UserProfile.objects.get(user=boot).break_glass
