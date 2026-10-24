"""OpenID Connect sign-in against a mock IdP: the redirect, state, nonce, PKCE and ID token checks."""

import time
from urllib.parse import parse_qs, urlsplit

import pytest
from authlib.oauth2.rfc7636 import create_s256_code_challenge
from django.conf import settings
from django.contrib.auth.models import User
from joserfc import jwt
from joserfc.jwk import RSAKey
from rest_framework.test import APIClient

from accounts.models import AuthProvider, ExternalIdentity, GroupMappingRule, UserGroup
from accounts.providers import ProviderError, oidc
from audit.models import AuditLog

ISSUER = 'https://idp.example.com'
DISCOVERY = f'{ISSUER}/.well-known/openid-configuration'
CLIENT = 'devicevault'


class MockIdP:
    """Discovery, JWKS, a token endpoint (checking the code and PKCE verifier) and userinfo."""

    def __init__(self):
        self.key = RSAKey.generate_key(2048, parameters={'kid': 'k1'})
        self.codes = {}  # code -> (challenge, claims)
        self.claims = {}
        self.token_overrides = {}
        self.userinfo = None
        self.jwks_fetches = 0

    def get_json(self, url, timeout, headers=None):
        if url == DISCOVERY:
            return {
                'issuer': ISSUER,
                'authorization_endpoint': f'{ISSUER}/authorize',
                'token_endpoint': f'{ISSUER}/token',
                'jwks_uri': f'{ISSUER}/jwks',
                'userinfo_endpoint': f'{ISSUER}/userinfo',
                'end_session_endpoint': f'{ISSUER}/logout',
            }
        if url == f'{ISSUER}/jwks':
            self.jwks_fetches += 1
            return {'keys': [self.key.as_dict(private=False)]}
        if url == f'{ISSUER}/userinfo':
            assert headers == {'Authorization': 'Bearer access-1'}
            if self.userinfo is None:
                raise ProviderError('no userinfo')
            return self.userinfo
        raise ProviderError(f'unexpected {url}')

    def authorize(self, location: str) -> dict:
        """What the IdP does with the browser: remember the challenge, hand back a code."""
        query = {k: v[0] for k, v in parse_qs(urlsplit(location).query).items()}
        assert query['code_challenge_method'] == 'S256' and query['client_id'] == CLIENT
        code = f'code-{len(self.codes)}'
        self.codes[code] = (query['code_challenge'], query['nonce'])
        return {'code': code, 'state': query['state']}

    def sign(self, claims, key=None, kid='k1'):
        return jwt.encode({'alg': 'RS256', 'kid': kid}, claims, key or self.key)

    def post_form(self, url, data, timeout, auth=None):
        assert url == f'{ISSUER}/token' and auth == (CLIENT, 'shh')
        challenge, nonce = self.codes.pop(data['code'])
        if create_s256_code_challenge(data['code_verifier']) != challenge:
            raise ProviderError('token request refused: invalid_grant PKCE')
        now = int(time.time())
        claims = {
            'iss': ISSUER,
            'aud': CLIENT,
            'sub': 'sub-1',
            'iat': now,
            'exp': now + 300,
            'nonce': nonce,
            'preferred_username': 'dave',
            'email': 'dave@example.com',
            'given_name': 'Dave',
            'family_name': 'Tester',
            'groups': ['netops'],
            **self.claims,
        }
        claims = {k: v for k, v in claims.items() if v is not None}
        return {'id_token': self.sign(claims, **self.token_overrides), 'access_token': 'access-1'}


@pytest.fixture
def idp(monkeypatch):
    mock = MockIdP()
    oidc.forget_cache()
    monkeypatch.setattr(oidc, 'get_json', mock.get_json)
    monkeypatch.setattr(oidc, 'post_form', mock.post_form)
    yield mock
    oidc.forget_cache()


@pytest.fixture
def provider(db):
    return AuthProvider.objects.create(
        slug='entra',
        name='Entra ID',
        kind='oidc',
        config={'discovery_url': DISCOVERY, 'client_id': CLIENT, 'client_secret': 'shh', 'end_session': True},
    )


def begin(client, next_path='/devices'):
    reply = client.get('/api/auth/oidc/entra/login/', {'next': next_path})
    assert reply.status_code == 302, reply.content
    return reply['Location']


def finish(client, params):
    return client.get('/api/auth/oidc/entra/callback/', params)


def test_a_full_sign_in(idp, provider):
    operators = UserGroup.objects.create(name='Operators')
    GroupMappingRule.objects.create(provider=provider, external_group='netops', user_group=operators)
    client = APIClient()

    location = begin(client)
    assert location.startswith(f'{ISSUER}/authorize?')
    query = parse_qs(urlsplit(location).query)
    assert query['redirect_uri'] == ['http://testserver/api/auth/oidc/entra/callback/']
    assert query['scope'] == ['openid profile email']

    reply = finish(client, idp.authorize(location))

    assert reply.status_code == 302 and reply['Location'] == '/devices'
    me = client.get('/api/auth/user/').json()
    assert (me['username'], me['email'], me['source']) == ('dave', 'dave@example.com', 'external')
    assert ExternalIdentity.objects.get(provider=provider).subject == 'sub-1'
    assert User.objects.get(username='dave').user_groups.get() == operators
    cookie = reply.cookies[settings.SESSION_COOKIE_NAME]
    assert cookie['samesite'] == 'Lax' and cookie['httponly']


def test_the_state_must_match_this_browser(idp, provider):
    client = APIClient()
    params = idp.authorize(begin(client))

    other_browser = finish(APIClient(), params)
    forged = finish(client, {**params, 'state': 'forged'})

    assert other_browser['Location'] == forged['Location'] == '/login?error=state'
    # The genuine state still works once, and only once.
    assert finish(client, params)['Location'] == '/devices'
    assert finish(client, params)['Location'] == '/login?error=state'


def test_stale_requests_are_refused(idp, provider, monkeypatch):
    client = APIClient()
    params = idp.authorize(begin(client))
    monkeypatch.setattr('accounts.oidc_views.time.time', lambda: time.time_ns() / 1e9 + 3600)

    assert finish(client, params)['Location'] == '/login?error=state'


@pytest.mark.parametrize(
    'claims',
    [
        {'nonce': 'replayed'},
        {'aud': 'someone-else'},
        {'iss': 'https://evil.example.com'},
        {'exp': int(time.time()) - 3600},
        {'sub': None},
        {'aud': [CLIENT, 'other'], 'azp': 'other'},
    ],
    ids=['nonce', 'audience', 'issuer', 'expired', 'no-subject', 'azp'],
)
def test_id_tokens_are_validated(idp, provider, claims):
    idp.claims = claims
    client = APIClient()

    reply = finish(client, idp.authorize(begin(client)))

    assert reply['Location'] == '/login?error=failed'
    assert client.get('/api/auth/user/').status_code == 401
    assert AuditLog.objects.get(action='auth.login').details['reason'] == 'invalid_token'


def test_signatures_must_come_from_the_idps_keys(idp, provider):
    idp.token_overrides = {'key': RSAKey.generate_key(2048, parameters={'kid': 'k1'})}
    client = APIClient()

    assert finish(client, idp.authorize(begin(client)))['Location'] == '/login?error=failed'
    assert idp.jwks_fetches == 2  # refetched once, in case the IdP rotated its keys


def test_the_pkce_verifier_must_match(idp, provider, monkeypatch):
    client = APIClient()
    params = idp.authorize(begin(client))
    session = client.session
    session['dv_oidc_pending'][0]['verifier'] = 'not-the-verifier'
    session.save()

    assert finish(client, params)['Location'] == '/login?error=failed'


def test_idp_errors_and_refusals_land_on_the_login_page(idp, provider):
    client = APIClient()
    begin(client)
    assert finish(client, {'error': 'access_denied', 'state': 'x'})['Location'] == '/login?error=denied'

    provider.login_group = 'devicevault-users'
    provider.save()
    assert finish(client, idp.authorize(begin(client)))['Location'] == '/login?error=refused'


def test_missing_claims_come_from_userinfo(idp, provider):
    idp.claims = {'groups': None, 'email': None}
    idp.userinfo = {'sub': 'sub-1', 'email': 'dave@corp.example.com', 'groups': ['ops']}
    provider.auto_create_groups = True
    provider.save()
    client = APIClient()

    finish(client, idp.authorize(begin(client)))

    user = User.objects.get(username='dave')
    assert user.email == 'dave@corp.example.com'
    assert list(user.user_groups.values_list('name', flat=True)) == ['entra:ops']


def test_entra_group_overage_is_logged(idp, provider, caplog):
    idp.claims = {'groups': None, '_claim_names': {'groups': 'src1'}}
    client = APIClient()

    finish(client, idp.authorize(begin(client)))

    assert 'oidc_groups_overage' in caplog.text
    assert client.get('/api/auth/user/').status_code == 200


def test_only_same_app_redirects_are_followed(idp, provider):
    client = APIClient()

    location = begin(client, next_path='//evil.example.com/x')

    assert finish(client, idp.authorize(location))['Location'] == '/'


def test_disabled_or_unknown_providers_are_not_found(idp, provider):
    provider.enabled = False
    provider.save()

    assert APIClient().get('/api/auth/oidc/entra/login/').status_code == 404
    assert APIClient().get('/api/auth/oidc/nope/callback/').status_code == 404


def test_signing_out_can_end_the_idp_session(idp, provider):
    client = APIClient()
    finish(client, idp.authorize(begin(client)))
    client.get('/api/auth/csrf/')

    reply = client.post('/api/auth/logout/')

    assert reply.status_code == 200
    target = urlsplit(reply.json()['redirect'])
    assert f'{target.scheme}://{target.netloc}{target.path}' == f'{ISSUER}/logout'
    assert parse_qs(target.query)['post_logout_redirect_uri'] == ['http://testserver/login']
    assert client.get('/api/auth/user/').status_code == 401


def test_the_provider_shows_its_redirect_uri_and_tests_discovery(idp, provider, admin_client):
    row = admin_client.get(f'/api/auth-providers/{provider.id}/').json()
    result = admin_client.post(f'/api/auth-providers/{provider.id}/test/', {}, format='json').json()

    assert row['redirect_uri'] == 'http://testserver/api/auth/oidc/entra/callback/'
    assert row['config']['client_secret'] is None and row['secrets_set'] == ['client_secret']
    assert result['ok'] and result['issuer'] == ISSUER and result['signing_keys'] == 1


def test_discovery_must_be_https(admin_client):
    reply = admin_client.post(
        '/api/auth-providers/',
        {'slug': 'x', 'name': 'X', 'kind': 'oidc', 'config': {'discovery_url': 'http://idp/', 'client_id': 'c'}},
        format='json',
    )

    assert reply.status_code == 400 and 'https' in str(reply.json()['config'])


def test_the_login_page_offers_redirect_providers(provider):
    [entry] = APIClient().get('/api/auth/config/').json()['providers']

    assert entry == {'slug': 'entra', 'name': 'Entra ID', 'kind': 'oidc', 'password_login': False}
