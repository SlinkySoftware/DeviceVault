"""Session lifetimes: an idle timeout and an absolute lifetime, both enforced server side.

The session records when it signed in and when it was last used. The last-use
time is refreshed at most once a minute, so most requests do not write the
session. Expired sessions are ended (and audited) on their next request; the
scheduler leader prunes the ones that never come back.
"""

import logging
import time

from django.conf import settings
from django.contrib.auth import SESSION_KEY, logout

from audit.log import record

logger = logging.getLogger('devicevault.sessions')

LOGIN_AT = 'dv_login_at'
SEEN_AT = 'dv_seen_at'
TOUCH_SECONDS = 60


def start(request) -> None:
    """Stamp a freshly signed-in session."""
    now = int(time.time())
    request.session[LOGIN_AT] = now
    request.session[SEEN_AT] = now


def expiry_reason(session, now: float | None = None) -> str | None:
    """Why ``session`` (a mapping) has timed out, or None while it is valid."""
    now = time.time() if now is None else now
    login_at, seen_at = session.get(LOGIN_AT), session.get(SEEN_AT)
    if login_at is not None and now - login_at > settings.DEVICEVAULT_SESSION_MAX_HOURS * 3600:
        return 'lifetime'
    if seen_at is not None and now - seen_at > settings.DEVICEVAULT_SESSION_IDLE_MIN * 60:
        return 'idle'
    return None


class SessionTimeoutMiddleware:
    """Ends timed-out sessions before the request is handled. Goes after AuthenticationMiddleware."""

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        session = request.session
        if SESSION_KEY in session:
            now = time.time()
            reason = expiry_reason(session, now)
            if reason:
                user = request.user if request.user.is_authenticated else None
                record(request, 'auth.session_expired', actor=user, details={'reason': reason})
                logout(request)
            elif LOGIN_AT not in session:
                start(request)
            elif now - session.get(SEEN_AT, 0) > TOUCH_SECONDS:
                session[SEEN_AT] = int(now)
        return self.get_response(request)


def prune_expired() -> None:
    """Delete sessions past their stored expiry (run by the scheduler leader)."""
    from importlib import import_module

    engine = import_module(settings.SESSION_ENGINE)
    engine.SessionStore.clear_expired()
