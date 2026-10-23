"""API for Flower endpoints (administrators only) and the check nginx makes before proxying one."""

import re
from urllib.parse import urlsplit

from django.contrib.auth.models import User
from django.core import signing
from django.utils.crypto import constant_time_compare, salted_hmac
from rest_framework import decorators, permissions, response, serializers, status, viewsets

from api.permissions import IsAdmin, is_admin
from monitoring.models import SLUG_PATTERN, FlowerEndpoint

# The UI gets this cookie just before opening a proxied Flower, since a new tab
# carries no API token. It is scoped to the endpoint's path and bound to the
# API token, so signing out ends it too.
SESSION_COOKIE = 'dv_flower'
SESSION_SALT = 'devicevault.monitoring.flower'
SESSION_SECONDS = 8 * 3600

UPSTREAM_HEADER = 'X-Flower-Upstream'
_PROXIED_PATH = re.compile(rf'^/flower/({SLUG_PATTERN})/')


class FlowerEndpointSerializer(serializers.ModelSerializer):
    link = serializers.CharField(read_only=True)

    class Meta:
        model = FlowerEndpoint
        fields = ['id', 'name', 'slug', 'url', 'proxied', 'link', 'created_at', 'updated_at']

    def validate(self, attrs):
        url = attrs.get('url', getattr(self.instance, 'url', ''))
        proxied = attrs.get('proxied', getattr(self.instance, 'proxied', True))
        parts = urlsplit(url)
        if parts.scheme not in ('http', 'https'):
            raise serializers.ValidationError({'url': 'Use an http:// or https:// address.'})
        # nginx forwards the whole request path (/flower/<slug>/...), and can't log in to the upstream.
        if proxied and (parts.path not in ('', '/') or parts.query or parts.fragment or parts.username):
            raise serializers.ValidationError(
                {'url': 'A proxied endpoint needs just scheme, host and port, e.g. http://flower:5555.'}
            )
        return attrs


def _token_digest(key: str) -> str:
    return salted_hmac(SESSION_SALT, key, algorithm='sha256').hexdigest()


class FlowerEndpointViewSet(viewsets.ModelViewSet):
    """Flower endpoints.

    - POST {id}/session/: set the cookie that lets this browser open a proxied endpoint
    """

    queryset = FlowerEndpoint.objects.all()
    serializer_class = FlowerEndpointSerializer
    permission_classes = [IsAdmin]

    @decorators.action(detail=True, methods=['post'])
    def session(self, request, pk=None):
        endpoint = self.get_object()
        if not endpoint.proxied:
            return response.Response({'error': 'This endpoint is not proxied'}, status=status.HTTP_400_BAD_REQUEST)
        token = getattr(request.auth, 'key', None)
        if not token:
            return response.Response({'error': 'Sign in through the UI first'}, status=status.HTTP_400_BAD_REQUEST)
        value = signing.dumps(
            {'user': request.user.pk, 'slug': endpoint.slug, 'token': _token_digest(token)}, salt=SESSION_SALT
        )
        resp = response.Response({'link': endpoint.link})
        resp.set_cookie(
            SESSION_COOKIE,
            value,
            max_age=SESSION_SECONDS,
            path=endpoint.path,
            secure=request.is_secure(),
            httponly=True,
            samesite='Strict',
        )
        return resp


def _session_user(request, slug: str) -> User | None:
    """The administrator whose cookie for ``slug`` is on this request, if still valid."""
    try:
        claims = signing.loads(request.COOKIES.get(SESSION_COOKIE, ''), salt=SESSION_SALT, max_age=SESSION_SECONDS)
    except signing.BadSignature:  # includes expiry
        return None
    if claims.get('slug') != slug:
        return None
    user = User.objects.filter(pk=claims.get('user'), is_active=True).select_related('auth_token').first()
    token = getattr(user, 'auth_token', None) if user else None
    if not token or not constant_time_compare(_token_digest(token.key), claims.get('token', '')):
        return None
    return user if is_admin(user) else None


@decorators.api_view(['GET'])
@decorators.authentication_classes([])
@decorators.permission_classes([permissions.AllowAny])  # authorised by the signed session cookie below
def flower_auth(request):
    """nginx ``auth_request`` for ``/flower/<slug>/``: 204 plus the upstream, or 401/403.

    nginx passes the original path in ``X-Original-URI``.
    """
    match = _PROXIED_PATH.match(request.headers.get('X-Original-URI', ''))
    endpoint = FlowerEndpoint.objects.filter(slug=match[1], proxied=True).first() if match else None
    if endpoint is None:
        return response.Response(status=status.HTTP_403_FORBIDDEN)
    if _session_user(request, endpoint.slug) is None:
        return response.Response(status=status.HTTP_401_UNAUTHORIZED)
    resp = response.Response(status=status.HTTP_204_NO_CONTENT)
    resp[UPSTREAM_HEADER] = endpoint.url.rstrip('/')
    return resp
