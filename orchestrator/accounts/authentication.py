"""API authentication: a bearer API token, else Django's server-side session (CSRF on unsafe methods)."""

from rest_framework import authentication, exceptions

from accounts import tokens
from audit.log import client_ip

INVALID_TOKEN = 'Invalid or expired token.'


class TokenAuthentication(authentication.BaseAuthentication):
    """``Authorization: Bearer dvt_...`` (accounts.tokens).

    Needs no CSRF token: a browser never sends the header on its own. Every
    refusal gets the same 401, whatever the cause; the cause goes to the audit log.
    A token whose scopes the view does not accept gets 403.
    """

    keyword = b'bearer'

    def authenticate(self, request):
        header = authentication.get_authorization_header(request).split()
        if not header or header[0].lower() != self.keyword:
            return None
        address = client_ip(request)
        if len(header) != 2:
            tokens.refused(request, '', 'malformed', address)
            raise exceptions.AuthenticationFailed(INVALID_TOKEN)
        try:
            raw = header[1].decode('ascii')
        except UnicodeDecodeError:
            raw = ''
        token, prefix, cause = tokens.check(raw, address)
        if token is None:
            tokens.refused(request, prefix, cause, address)
            raise exceptions.AuthenticationFailed(INVALID_TOKEN)
        view = (getattr(request, 'parser_context', None) or {}).get('view')
        if view is not None and not tokens.allows(token, view):
            raise exceptions.PermissionDenied('This token may not be used here.')
        if tokens.over_rate(token):
            raise exceptions.Throttled()
        tokens.touch(request, token, address)
        return token.user, token

    def authenticate_header(self, request):
        return 'Bearer'


class SessionAuthentication(authentication.SessionAuthentication):
    """DRF's session authentication, answering unauthenticated requests with 401 rather than 403.

    The UI treats 401 as "signed out" and sends the user to the login page.
    """

    def authenticate_header(self, request):
        return 'Session'
