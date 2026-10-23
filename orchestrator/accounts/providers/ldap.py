"""LDAP and Active Directory sign-in, with python-ldap directly (search, then bind as the user found).

1. Bind as the service account (or anonymously) to the first server that answers.
2. Search ``user_base_dn`` with ``user_filter``, the username escaped into it. Exactly one entry must match.
3. Bind as that entry with the password, on a connection of its own.
4. Read the identity attribute (the link to the user), the profile attributes and the groups:
   ``memberOf`` values, or a group search; for AD, optionally nested via LDAP_MATCHING_RULE_IN_CHAIN.
"""

import contextlib
import logging
import os
import tempfile
import uuid
from collections.abc import Iterator
from typing import Literal

import ldap
import ldap.dn
from ldap.filter import escape_filter_chars
from pydantic import BaseModel, ConfigDict, Field, SecretStr, field_validator, model_validator

from accounts.providers.base import ExternalLogin, ProviderError, ProviderKind

logger = logging.getLogger('devicevault.auth.ldap')

IN_CHAIN = '1.2.840.113556.1.4.1941'  # AD: LDAP_MATCHING_RULE_IN_CHAIN


class LdapConfig(BaseModel):
    """Settings of an LDAP or Active Directory provider."""

    model_config = ConfigDict(extra='forbid')

    server_uris: list[str] = Field(
        min_length=1,
        title='Servers',
        description='Tried in order, e.g. ldaps://dc1.example.com, ldaps://dc2.example.com',
    )
    start_tls: bool = Field(False, title='StartTLS', description='Upgrade ldap:// connections to TLS')
    verify_certificate: bool = Field(True, title='Verify the server certificate')
    ca_certificate: str = Field('', title='CA certificate (PEM)', description='Empty: the system trust store')
    bind_dn: str = Field('', title='Bind DN', description='Service account; empty binds anonymously')
    bind_password: SecretStr | None = Field(None, title='Bind password')
    user_base_dn: str = Field(min_length=1, title='User search base')
    user_filter: str = Field(
        '(&(objectClass=person)(uid={username}))',
        title='User filter',
        description='{username} is replaced by the escaped username; AD: (sAMAccountName={username})',
    )
    username_attribute: str = Field('uid', title='Username attribute', description='AD: sAMAccountName')
    email_attribute: str = Field('mail', title='Email attribute')
    first_name_attribute: str = Field('givenName', title='First name attribute')
    last_name_attribute: str = Field('sn', title='Last name attribute')
    identity_attribute: str = Field(
        'entryUUID', title='Identity attribute', description='Immutable id the user is linked by; AD: objectGUID'
    )
    group_source: Literal['member_of', 'search'] = Field(
        'member_of', title='Groups from', description="member_of: the user's memberOf attribute; search: a group search"
    )
    member_of_attribute: str = Field('memberOf', title='Member-of attribute')
    group_base_dn: str = Field('', title='Group search base', description='Empty: the user search base')
    group_filter: str = Field(
        '(&(objectClass=groupOfNames)(member={user_dn}))',
        title='Group filter',
        description='{user_dn} is replaced by the escaped user DN',
    )
    group_name_attribute: str = Field('cn', title='Group name attribute')
    nested_groups: bool = Field(
        False, title='Nested groups (Active Directory)', description='Include groups of groups (matching rule in chain)'
    )
    timeout_seconds: int = Field(10, ge=1, le=120, title='Timeout (seconds)')

    @field_validator('server_uris')
    @classmethod
    def _uris(cls, uris: list[str]) -> list[str]:
        for uri in uris:
            if not uri.startswith(('ldap://', 'ldaps://')):
                raise ValueError(f'{uri!r} must start with ldap:// or ldaps://')
        return uris

    @field_validator('user_filter')
    @classmethod
    def _user_filter(cls, value: str) -> str:
        if '{username}' not in value:
            raise ValueError('must contain {username}')
        return value

    @model_validator(mode='after')
    def _group_filter(self):
        if self.group_source == 'search' and not self.nested_groups and '{user_dn}' not in self.group_filter:
            raise ValueError('group_filter must contain {user_dn}')
        return self


def _text(values: list[bytes] | None) -> str:
    if not values:
        return ''
    return values[0].decode('utf-8', 'replace')


def _identity(attribute: str, values: list[bytes] | None) -> str:
    if not values:
        return ''
    raw = values[0]
    if attribute.lower() == 'objectguid' and len(raw) == 16:
        return str(uuid.UUID(bytes_le=raw))
    try:
        return raw.decode('utf-8')
    except UnicodeDecodeError:
        return raw.hex()


def _rdn_value(dn: str) -> str:
    """``CN=Network Admins,OU=Groups,...`` -> ``Network Admins``."""
    try:
        return ldap.dn.str2dn(dn)[0][0][1]
    except ldap.DECODING_ERROR, IndexError:
        return dn


class LdapKind(ProviderKind):
    key = 'ldap'
    name = 'LDAP / Active Directory'
    Config = LdapConfig
    password_login = True
    case_insensitive_groups = True

    # --- connections ---------------------------------------------------------------

    @contextlib.contextmanager
    def _ca_file(self, config: LdapConfig) -> Iterator[str | None]:
        if not config.ca_certificate.strip():
            yield None
            return
        handle, path = tempfile.mkstemp(suffix='.pem')
        try:
            with os.fdopen(handle, 'w') as out:
                out.write(config.ca_certificate)
            yield path
        finally:
            os.unlink(path)

    def _connect(self, config: LdapConfig, uri: str, ca_file: str | None):
        conn = ldap.initialize(uri)
        conn.set_option(ldap.OPT_PROTOCOL_VERSION, 3)
        conn.set_option(ldap.OPT_REFERRALS, 0)
        conn.set_option(ldap.OPT_NETWORK_TIMEOUT, float(config.timeout_seconds))
        conn.set_option(ldap.OPT_TIMEOUT, float(config.timeout_seconds))
        conn.set_option(
            ldap.OPT_X_TLS_REQUIRE_CERT, ldap.OPT_X_TLS_DEMAND if config.verify_certificate else ldap.OPT_X_TLS_NEVER
        )
        if ca_file:
            conn.set_option(ldap.OPT_X_TLS_CACERTFILE, ca_file)
        conn.set_option(ldap.OPT_X_TLS_NEWCTX, 0)  # applies the TLS options above; must come last
        if config.start_tls and uri.startswith('ldap://'):
            conn.start_tls_s()
        return conn

    def _service(self, config: LdapConfig, ca_file: str | None):
        """A connection bound as the service account, to the first server that answers, and its URI."""
        password = config.bind_password.get_secret_value() if config.bind_password else ''
        problems = []
        for uri in config.server_uris:
            try:
                conn = self._connect(config, uri, ca_file)
                conn.simple_bind_s(config.bind_dn, password)
                return conn, uri
            except ldap.INVALID_CREDENTIALS as exc:
                raise ProviderError(f'{uri}: the bind DN or password is wrong') from exc
            except ldap.LDAPError as exc:
                problems.append(f'{uri}: {_describe(exc)}')
        raise ProviderError('; '.join(problems) or 'no servers configured')

    # --- lookups ---------------------------------------------------------------------

    def _find_user(self, conn, config: LdapConfig, username: str) -> tuple[str, dict] | None:
        query = config.user_filter.replace('{username}', escape_filter_chars(username))
        attributes = [
            config.username_attribute,
            config.email_attribute,
            config.first_name_attribute,
            config.last_name_attribute,
            config.identity_attribute,
        ]
        if config.group_source == 'member_of':
            attributes.append(config.member_of_attribute)
        try:
            found = conn.search_ext_s(
                config.user_base_dn, ldap.SCOPE_SUBTREE, query, attributes, timeout=config.timeout_seconds, sizelimit=2
            )
        except ldap.SIZELIMIT_EXCEEDED:
            logger.warning('ldap_user_ambiguous', extra={'username': username})
            return None
        except ldap.LDAPError as exc:
            raise ProviderError(f'user search failed: {_describe(exc)}') from exc
        entries = [(dn, attrs) for dn, attrs in found if dn]  # drop search references
        if len(entries) != 1:
            if entries:
                logger.warning('ldap_user_ambiguous', extra={'username': username})
            return None
        return entries[0]

    def _groups(self, conn, config: LdapConfig, dn: str, attrs: dict) -> list[str]:
        if config.group_source == 'member_of' and not config.nested_groups:
            return sorted(
                {_rdn_value(value.decode('utf-8', 'replace')) for value in attrs.get(config.member_of_attribute, [])}
            )
        base = config.group_base_dn or config.user_base_dn
        escaped = escape_filter_chars(dn)
        if config.nested_groups:
            query = f'(member:{IN_CHAIN}:={escaped})'
        else:
            query = config.group_filter.replace('{user_dn}', escaped)
        try:
            found = conn.search_ext_s(
                base, ldap.SCOPE_SUBTREE, query, [config.group_name_attribute], timeout=config.timeout_seconds
            )
        except ldap.LDAPError as exc:
            raise ProviderError(f'group search failed: {_describe(exc)}') from exc
        return sorted({_text(attrs.get(config.group_name_attribute)) or _rdn_value(gdn) for gdn, attrs in found if gdn})

    def _login(self, conn, config: LdapConfig, dn: str, attrs: dict) -> ExternalLogin:
        subject = _identity(config.identity_attribute, attrs.get(config.identity_attribute))
        if not subject:
            raise ProviderError(f'the user has no {config.identity_attribute} to link by')
        return ExternalLogin(
            subject=subject,
            username=_text(attrs.get(config.username_attribute)),
            email=_text(attrs.get(config.email_attribute)),
            first_name=_text(attrs.get(config.first_name_attribute)),
            last_name=_text(attrs.get(config.last_name_attribute)),
            groups=self._groups(conn, config, dn, attrs),
        )

    # --- the ProviderKind interface ---------------------------------------------------

    def authenticate(self, config: LdapConfig, username: str, password: str) -> ExternalLogin | None:
        if not username or not password:
            return None  # an empty password would be an anonymous bind, which "succeeds"
        with self._ca_file(config) as ca_file:
            conn, uri = self._service(config, ca_file)
            try:
                entry = self._find_user(conn, config, username)
                if entry is None:
                    return None
                dn, attrs = entry
                user_conn = self._connect(config, uri, ca_file)
                try:
                    user_conn.simple_bind_s(dn, password)
                except ldap.INVALID_CREDENTIALS:
                    return None
                except ldap.LDAPError as exc:
                    raise ProviderError(f'user bind failed: {_describe(exc)}') from exc
                finally:
                    _unbind(user_conn)
                return self._login(conn, config, dn, attrs)
            finally:
                _unbind(conn)

    def test(self, config: LdapConfig, username: str = '') -> dict:
        with self._ca_file(config) as ca_file:
            conn, uri = self._service(config, ca_file)
            try:
                result: dict = {'server': uri, 'bound_as': config.bind_dn or '(anonymous)'}
                if username:
                    entry = self._find_user(conn, config, username)
                    if entry is None:
                        result['user'] = None
                    else:
                        login = self._login(conn, config, *entry)
                        result['user'] = {
                            'dn': entry[0],
                            'subject': login.subject,
                            'username': login.username,
                            'email': login.email,
                            'name': f'{login.first_name} {login.last_name}'.strip(),
                            'groups': login.groups,
                        }
                return result
            finally:
                _unbind(conn)


def _describe(exc: ldap.LDAPError) -> str:
    detail = exc.args[0] if exc.args and isinstance(exc.args[0], dict) else {}
    if not detail:
        return str(exc) or type(exc).__name__
    desc, info = detail.get('desc') or type(exc).__name__, detail.get('info')
    return f'{desc} ({info})' if info else desc


def _unbind(conn) -> None:
    with contextlib.suppress(ldap.LDAPError):
        conn.unbind_s()
