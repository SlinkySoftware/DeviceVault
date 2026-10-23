"""OpenID Connect sign-in: the redirect out to the IdP and the callback that starts the session.

Both are browser navigations, not API calls, so they answer with redirects:
into the SPA on success, or to ``/login?error=<code>`` on failure. The state,
nonce and PKCE verifier live in the (server-side) session between the two.
"""

import time

from django.http import Http404, HttpResponseRedirect
from django.utils.crypto import constant_time_compare
from rest_framework.permissions import AllowAny
from rest_framework.views import APIView

from accounts.api import start_session
from accounts.login import LoginRefused, accept
from accounts.models import AuthProvider
from accounts.providers import KINDS, ProviderError
from accounts.throttle import LOGIN
from audit.log import record
from audit.models import AuditLog

PENDING = 'dv_oidc_pending'
ID_TOKEN = 'dv_id_token'
PENDING_SECONDS = 600
MAX_PENDING = 5


def safe_next(value) -> str:
    """Only same-app paths (``/devices``), never ``//host`` or ``/\\host``."""
    if isinstance(value, str) and value.startswith('/') and not value.startswith(('//', '/\\')):
        return value
    return '/'


def callback_uri(request, provider: AuthProvider) -> str:
    return request.build_absolute_uri(f'/api/auth/oidc/{provider.slug}/callback/')


def _provider(slug: str) -> AuthProvider:
    provider = AuthProvider.objects.filter(slug=slug, kind=AuthProvider.OIDC, enabled=True).first()
    if provider is None:
        raise Http404
    return provider


def _failed(request, provider, reason: str, code: str, **details) -> HttpResponseRedirect:
    """Audit a failed sign-in and send the browser to the login page with ``?error=<code>``."""
    record(
        request,
        LOGIN,
        outcome=AuditLog.FAILURE,
        actor_name='',
        details={'provider': provider.slug, 'reason': reason, **details},
    )
    return HttpResponseRedirect(f'/login?error={code}')


class OidcLoginView(APIView):
    """GET /api/auth/oidc/<slug>/login/?next=/path: send the browser to the IdP."""

    authentication_classes = []
    permission_classes = [AllowAny]

    def get(self, request, slug):
        provider = _provider(slug)
        kind = KINDS[provider.kind]
        try:
            url, pending = kind.start(kind.config(provider.config), callback_uri(request, provider))
        except ProviderError as exc:
            return _failed(request, provider, 'unavailable', 'unavailable', error=str(exc))
        pending.update(slug=provider.slug, next=safe_next(request.query_params.get('next')), at=time.time())
        kept = [entry for entry in request.session.get(PENDING, []) if time.time() - entry['at'] < PENDING_SECONDS]
        request.session[PENDING] = [*kept[-(MAX_PENDING - 1) :], pending]
        return HttpResponseRedirect(url)


class OidcCallbackView(APIView):
    """GET /api/auth/oidc/<slug>/callback/?code=&state=: finish signing in."""

    authentication_classes = []
    permission_classes = [AllowAny]

    def get(self, request, slug):
        provider = _provider(slug)
        kind = KINDS[provider.kind]
        state = request.query_params.get('state', '')
        entries = request.session.get(PENDING, [])
        pending = next(
            (e for e in entries if e['slug'] == provider.slug and state and constant_time_compare(e['state'], state)),
            None,
        )
        if pending is not None:
            request.session[PENDING] = [e for e in entries if e is not pending]

        if request.query_params.get('error'):
            return _failed(request, provider, 'idp_error', 'denied', error=request.query_params['error'][:100])
        if pending is None or time.time() - pending['at'] > PENDING_SECONDS:
            return _failed(request, provider, 'bad_state', 'state')
        try:
            login, id_token = kind.complete(
                kind.config(provider.config),
                callback_uri(request, provider),
                request.query_params.get('code', ''),
                pending,
            )
        except ProviderError as exc:
            return _failed(request, provider, 'invalid_token', 'failed', error=str(exc)[:300])
        try:
            user, changes = accept(provider, login)
        except LoginRefused as exc:
            return _failed(request, provider, exc.reason, 'refused', subject=login.subject)

        start_session(request, user, provider, **changes)
        request.session[ID_TOKEN] = id_token
        return HttpResponseRedirect(pending['next'])
