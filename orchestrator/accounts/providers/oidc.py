"""OpenID Connect sign-in (Entra ID, Okta, Authentik, any compliant IdP): Authorization Code with PKCE.

1. ``start``: a random state, nonce and PKCE verifier; the browser is sent to the
   IdP's authorization endpoint (from discovery) with the S256 challenge.
2. ``complete``: the code is exchanged at the token endpoint with the verifier.
   The ID token's signature is checked against the IdP's JWKS (refetched once
   for an unknown key id), and its issuer, audience, expiry and nonce validated.
   Claims missing from the ID token (often groups or names) come from userinfo.

The groups claim may be absent when Entra ID has too many groups to list (it then
sends an overage pointer); this is logged, and the user signs in without groups.
Configure the app registration to emit only groups assigned to the application.
"""

import logging
import time
from typing import Any
from urllib.parse import urlencode, urlsplit

import requests
from authlib.common.security import generate_token
from authlib.oauth2.rfc7636 import create_s256_code_challenge
from joserfc import jwt
from joserfc.errors import JoseError
from joserfc.jwk import KeySet
from pydantic import BaseModel, ConfigDict, Field, SecretStr, field_validator

from accounts.providers.base import ExternalLogin, ProviderError, ProviderKind

logger = logging.getLogger('devicevault.auth.oidc')

ALGORITHMS = ['RS256', 'RS384', 'RS512', 'PS256', 'PS384', 'PS512', 'ES256', 'ES384', 'ES512']
CACHE_SECONDS = 3600
LEEWAY_SECONDS = 60


class OidcConfig(BaseModel):
    """Settings of an OpenID Connect provider."""

    model_config = ConfigDict(extra='forbid')

    discovery_url: str = Field(
        title='Discovery URL',
        description='e.g. https://login.microsoftonline.com/<tenant>/v2.0/.well-known/openid-configuration',
    )
    client_id: str = Field(min_length=1, title='Client ID')
    client_secret: SecretStr | None = Field(None, title='Client secret', description='Empty for a public client')
    scopes: list[str] = Field(['openid', 'profile', 'email'], title='Scopes')
    username_claim: str = Field('preferred_username', title='Username claim')
    email_claim: str = Field('email', title='Email claim')
    first_name_claim: str = Field('given_name', title='First name claim')
    last_name_claim: str = Field('family_name', title='Last name claim')
    groups_claim: str = Field('groups', title='Groups claim')
    end_session: bool = Field(
        False, title='Sign out at the IdP', description="Signing out of DeviceVault also ends the IdP's session"
    )
    timeout_seconds: int = Field(10, ge=1, le=60, title='Timeout (seconds)')

    @field_validator('discovery_url')
    @classmethod
    def _https(cls, value: str) -> str:
        parts = urlsplit(value)
        if parts.scheme != 'https' and not (parts.scheme == 'http' and parts.hostname in ('localhost', '127.0.0.1')):
            raise ValueError('must be an https:// URL')
        return value

    @field_validator('scopes')
    @classmethod
    def _openid(cls, value: list[str]) -> list[str]:
        return value if 'openid' in value else ['openid', *value]


# --- HTTP (patched by tests with a mock IdP) ----------------------------------------------


def get_json(url: str, timeout: int, headers: dict | None = None) -> dict:
    try:
        reply = requests.get(url, timeout=timeout, headers=headers)
        reply.raise_for_status()
        return reply.json()
    except (requests.RequestException, ValueError) as exc:
        raise ProviderError(f'{url}: {exc}') from exc


def post_form(url: str, data: dict, timeout: int, auth: tuple[str, str] | None = None) -> dict:
    try:
        reply = requests.post(url, data=data, auth=auth, timeout=timeout, headers={'Accept': 'application/json'})
    except requests.RequestException as exc:
        raise ProviderError(f'{url}: {exc}') from exc
    try:
        body = reply.json()
    except ValueError as exc:
        raise ProviderError(f'{url}: HTTP {reply.status_code}, not JSON') from exc
    if reply.status_code >= 400 or 'error' in body:
        raise ProviderError(f'token request refused: {body.get("error")} {body.get("error_description", "")}'.strip())
    return body


_cache: dict[str, tuple[float, Any]] = {}


def _cached(key: str, load, refresh: bool = False):
    hit = _cache.get(key)
    if hit and not refresh and time.monotonic() - hit[0] < CACHE_SECONDS:
        return hit[1]
    value = load()
    _cache[key] = (time.monotonic(), value)
    return value


def forget_cache() -> None:
    _cache.clear()


class OidcKind(ProviderKind):
    key = 'oidc'
    name = 'OpenID Connect'
    Config = OidcConfig
    password_login = False

    def metadata(self, config: OidcConfig, refresh: bool = False) -> dict:
        def load():
            data = get_json(config.discovery_url, config.timeout_seconds)
            missing = [k for k in ('issuer', 'authorization_endpoint', 'token_endpoint', 'jwks_uri') if not data.get(k)]
            if missing:
                raise ProviderError(f'discovery document lacks {", ".join(missing)}')
            return data

        return _cached(f'meta:{config.discovery_url}', load, refresh)

    def keys(self, config: OidcConfig, refresh: bool = False) -> KeySet:
        uri = self.metadata(config)['jwks_uri']

        def load():
            try:
                return KeySet.import_key_set(get_json(uri, config.timeout_seconds))
            except (JoseError, ValueError, KeyError, TypeError) as exc:
                raise ProviderError(f'unusable JWKS at {uri}: {exc}') from exc

        return _cached(f'jwks:{uri}', load, refresh)

    # --- the flow -----------------------------------------------------------------------

    def start(self, config: OidcConfig, redirect_uri: str) -> tuple[str, dict]:
        """The authorization URL to send the browser to, and what to keep in the session for ``complete``."""
        pending = {'state': generate_token(32), 'nonce': generate_token(32), 'verifier': generate_token(64)}
        query = {
            'response_type': 'code',
            'client_id': config.client_id,
            'redirect_uri': redirect_uri,
            'scope': ' '.join(config.scopes),
            'state': pending['state'],
            'nonce': pending['nonce'],
            'code_challenge': create_s256_code_challenge(pending['verifier']),
            'code_challenge_method': 'S256',
        }
        endpoint = self.metadata(config)['authorization_endpoint']
        return f'{endpoint}{"&" if "?" in endpoint else "?"}{urlencode(query)}', pending

    def complete(self, config: OidcConfig, redirect_uri: str, code: str, pending: dict) -> tuple[ExternalLogin, str]:
        """Exchange ``code`` and validate the ID token. Returns the login and the raw ID token."""
        meta = self.metadata(config)
        data = {
            'grant_type': 'authorization_code',
            'code': code,
            'redirect_uri': redirect_uri,
            'client_id': config.client_id,
            'code_verifier': pending['verifier'],
        }
        auth = (config.client_id, config.client_secret.get_secret_value()) if config.client_secret else None
        tokens = post_form(meta['token_endpoint'], data, config.timeout_seconds, auth=auth)
        id_token = tokens.get('id_token')
        if not id_token:
            raise ProviderError('the token response has no ID token')
        claims = self.validate_id_token(config, id_token, pending['nonce'])

        wanted = (config.username_claim, config.email_claim, config.groups_claim)
        if (
            any(claim not in claims for claim in wanted)
            and meta.get('userinfo_endpoint')
            and tokens.get('access_token')
        ):
            try:
                info = get_json(
                    meta['userinfo_endpoint'],
                    config.timeout_seconds,
                    headers={'Authorization': f'Bearer {tokens["access_token"]}'},
                )
            except ProviderError as exc:
                # Only fills in claims: sign in with what the ID token has.
                logger.warning('oidc_userinfo_unavailable', extra={'error': str(exc)})
                info = {}
            if info.get('sub') == claims['sub']:
                claims = {**info, **claims}
        return self.login_from_claims(config, claims), id_token

    def validate_id_token(self, config: OidcConfig, id_token: str, nonce: str) -> dict:
        issuer = self.metadata(config)['issuer']
        try:
            try:
                token = jwt.decode(id_token, self.keys(config), algorithms=ALGORITHMS)
            except JoseError:
                # The IdP may have rotated its keys since they were cached.
                token = jwt.decode(id_token, self.keys(config, refresh=True), algorithms=ALGORITHMS)
            jwt.JWTClaimsRegistry(
                leeway=LEEWAY_SECONDS,
                iss={'essential': True, 'value': issuer},
                aud={'essential': True, 'value': config.client_id},
                sub={'essential': True},
                exp={'essential': True},
                nonce={'essential': True, 'value': nonce},
            ).validate(token.claims)
        except (JoseError, ValueError) as exc:
            raise ProviderError(f'invalid ID token: {exc}') from exc
        claims = dict(token.claims)
        audiences = claims['aud'] if isinstance(claims['aud'], list) else [claims['aud']]
        if len(audiences) > 1 and claims.get('azp') != config.client_id:
            raise ProviderError('invalid ID token: issued for another party (azp)')
        return claims

    def login_from_claims(self, config: OidcConfig, claims: dict) -> ExternalLogin:
        groups = claims.get(config.groups_claim)
        if groups is None and config.groups_claim in (claims.get('_claim_names') or {}):
            logger.warning('oidc_groups_overage', extra={'sub': claims.get('sub')})
        if isinstance(groups, str):
            groups = [groups]
        return ExternalLogin(
            subject=str(claims['sub']),
            username=str(claims.get(config.username_claim) or claims.get('email') or claims['sub']),
            email=str(claims.get(config.email_claim) or ''),
            first_name=str(claims.get(config.first_name_claim) or ''),
            last_name=str(claims.get(config.last_name_claim) or ''),
            groups=sorted({str(group) for group in groups or []}),
        )

    def end_session_url(self, config: OidcConfig, id_token: str, after: str) -> str | None:
        if not config.end_session:
            return None
        try:
            endpoint = self.metadata(config).get('end_session_endpoint')
        except ProviderError:
            return None
        if not endpoint:
            return None
        query = urlencode({'id_token_hint': id_token, 'post_logout_redirect_uri': after, 'client_id': config.client_id})
        return f'{endpoint}{"&" if "?" in endpoint else "?"}{query}'

    def test(self, config: OidcConfig, username: str = '') -> dict:
        meta = self.metadata(config, refresh=True)
        keys = self.keys(config, refresh=True)
        return {
            'server': meta['issuer'],
            'issuer': meta['issuer'],
            'authorization_endpoint': meta['authorization_endpoint'],
            'token_endpoint': meta['token_endpoint'],
            'end_session_endpoint': meta.get('end_session_endpoint'),
            'signing_keys': len(keys.keys),
        }
