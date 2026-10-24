"""API authentication: Django's server-side session, with CSRF checks on unsafe methods."""

from rest_framework import authentication


class SessionAuthentication(authentication.SessionAuthentication):
    """DRF's session authentication, answering unauthenticated requests with 401 rather than 403.

    The UI treats 401 as "signed out" and sends the user to the login page.
    """

    def authenticate_header(self, request):
        return 'Session'
