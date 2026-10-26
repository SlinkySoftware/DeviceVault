"""API tokens: issuing, checking, scopes, rate limits and the audit of their use.

A token is ``dvt_<prefix>_<secret>``. The prefix finds the row and appears in
lists and audit entries; only the SHA-256 of the secret is stored. Scopes narrow
what a token reaches (each view declares ``token_scopes``), never what its user
may do there. Use is audited the first time a token is seen from an address,
and refusals at most once a minute per address, so polling does not flood the
audit log.
"""

import ipaddress
import logging
import secrets
import string
import time
from datetime import timedelta
from functools import cache

from django.conf import settings
from django.core.exceptions import ImproperlyConfigured
from django.utils import timezone
from django.utils.crypto import constant_time_compare
from redis import Redis
from redis.exceptions import RedisError

from accounts.models import ApiToken
from audit.log import record
from audit.models import AuditLog
from devicevault_protocol import monitoring

logger = logging.getLogger('devicevault.tokens')

PREFIX = monitoring.TOKEN_PREFIX
PREFIX_LENGTH = monitoring.TOKEN_PREFIX_LENGTH
DEFAULT_DAYS = 90
MAX_LIVE_PER_USER = 20
MAX_NETWORKS = 20
MAX_ADDRESSES = 100
TOUCH_SECONDS = 60
REFUSAL_AUDIT_SECONDS = 60

DEFAULT_VIEW_SCOPES = (ApiToken.API,)

_PREFIX_ALPHABET = string.ascii_lowercase + string.digits
_PERIODS = {'sec': 1, 'min': 60, 'hour': 3600}


def _redis() -> Redis:
    return Redis.from_url(settings.DEVICEVAULT_BUS.redis_url, socket_connect_timeout=2, socket_timeout=2)


@cache
def rate() -> tuple[int, int]:
    """``DV_API_TOKEN_RATE`` as (requests, seconds)."""
    value = settings.DEVICEVAULT_API_TOKEN_RATE
    try:
        count, period = value.split('/')
        return int(count), _PERIODS[period]
    except ValueError, KeyError:
        raise ImproperlyConfigured(f'DV_API_TOKEN_RATE must look like 600/min, not {value!r}') from None


digest = monitoring.token_digest
parse = monitoring.parse_token


def issue(user, *, name: str, scopes, expires_at, allowed_networks=(), created_by=None) -> tuple[ApiToken, str]:
    """Create a token for ``user``. Returns the row and the token string, which is never stored."""
    while True:
        prefix = ''.join(secrets.choice(_PREFIX_ALPHABET) for _ in range(PREFIX_LENGTH))
        if not ApiToken.objects.filter(prefix=prefix).exists():
            break
    secret = secrets.token_urlsafe(32)
    token = ApiToken.objects.create(
        user=user,
        name=name,
        prefix=prefix,
        digest=digest(secret),
        scopes=normalise_scopes(scopes),
        allowed_networks=list(allowed_networks),
        expires_at=expires_at,
        created_by=created_by,
    )
    return token, f'{PREFIX}_{prefix}_{secret}'


def normalise_scopes(scopes) -> list[str]:
    """Known scopes in a fixed order; ``monitoring_platform`` brings ``monitoring`` with it."""
    wanted = set(scopes)
    if ApiToken.MONITORING_PLATFORM in wanted:
        wanted.add(ApiToken.MONITORING)
    return [scope for scope in ApiToken.SCOPES if scope in wanted]


def is_live(token: ApiToken, now=None) -> bool:
    return token.revoked_at is None and token.expires_at > (now or timezone.now())


def address_allowed(token: ApiToken, address: str | None) -> bool:
    if not token.allowed_networks:
        return True
    if address is None:
        return False
    ip = ipaddress.ip_address(address)
    return any(ip in ipaddress.ip_network(network, strict=False) for network in token.allowed_networks)


def check(raw: str, address: str | None) -> tuple[ApiToken | None, str, str]:
    """The live token ``raw`` names, usable from ``address``.

    Returns (token, prefix, cause): the token is None when refused, with the cause
    for the audit log. Every refusal looks the same to the caller.
    """
    parsed = parse(raw)
    if parsed is None:
        return None, '', 'malformed'
    prefix, secret = parsed
    token = ApiToken.objects.select_related('user').filter(prefix=prefix).first()
    if token is None or not constant_time_compare(token.digest, digest(secret)):
        return None, prefix, 'unknown'
    if token.revoked_at is not None:
        return None, prefix, 'revoked'
    if token.expires_at <= timezone.now():
        return None, prefix, 'expired'
    if not token.user.is_active:
        return None, prefix, 'inactive_user'
    if not address_allowed(token, address):
        return None, prefix, 'network'
    return token, prefix, ''


def view_scopes(view) -> tuple[str, ...]:
    """The token scopes ``view`` (a view class or instance) accepts."""
    return tuple(getattr(view, 'token_scopes', DEFAULT_VIEW_SCOPES))


def allows(token: ApiToken, view) -> bool:
    return bool(set(token.scopes) & set(view_scopes(view)))


def token_scopes(*scopes: str):
    """Set ``token_scopes`` on a function view made with ``@api_view`` (apply it above the decorator)."""
    unknown = set(scopes) - set(ApiToken.SCOPES)
    if unknown:
        raise ValueError(f'Unknown token scopes {sorted(unknown)}')

    def decorate(view):
        view.cls.token_scopes = tuple(scopes)
        return view

    return decorate


def over_rate(token: ApiToken) -> bool:
    """Count a request against the token's limit; True once it is over. Allows the request if Redis is down."""
    limit, period = rate()
    window = int(time.time() // period)
    key = f'dv:token:rate:{token.prefix}:{window}'
    try:
        redis = _redis()
        count = redis.incr(key)
        if count == 1:
            redis.expire(key, period * 2)
    except RedisError as exc:
        logger.warning('token_rate_unavailable', extra={'error': str(exc)})
        return False
    return count > limit


def touch(request, token: ApiToken, address: str | None) -> None:
    """Note a use: last used (at most once a minute), and audit the first use from a new address."""
    now = timezone.now()
    changes = {}
    if address and address not in token.addresses:
        token.addresses = [*token.addresses, address][-MAX_ADDRESSES:]
        changes['addresses'] = token.addresses
        record(
            _plain(request),
            'token.use',
            resource=token.prefix,
            actor=token.user,
            details={'token': token.prefix, 'name': token.name, 'address': address},
        )
    stale = token.last_used_at is None or now - token.last_used_at > timedelta(seconds=TOUCH_SECONDS)
    if changes or stale or token.last_used_address != address:
        token.last_used_at, token.last_used_address = now, address
        changes.update(last_used_at=now, last_used_address=address)
        ApiToken.objects.filter(pk=token.pk).update(**changes)


def refused(request, prefix: str, cause: str, address: str | None, *, receiver: str = '') -> None:
    """Audit a refused token, at most once a minute per address (and receiver)."""
    key = f'dv:token:refused:{receiver}:{address}'
    try:
        if not _redis().set(key, 1, nx=True, ex=REFUSAL_AUDIT_SECONDS):
            return
    except RedisError as exc:
        logger.warning('token_refusal_unavailable', extra={'error': str(exc)})
    details = {'cause': cause, 'address': address}
    if prefix:
        details['token'] = prefix
    if receiver:
        details['receiver'] = receiver
    record(_plain(request), 'token.refused', resource=prefix, outcome=AuditLog.DENIED, details=details)


def _plain(request):
    """The Django request behind a DRF one. Mid-authentication, reading the DRF request's user would re-enter it."""
    return getattr(request, '_request', request)


def snapshot(token: ApiToken) -> dict:
    return {
        'token': token.prefix,
        'name': token.name,
        'user': token.user.username,
        'scopes': token.scopes,
        'allowed_networks': token.allowed_networks,
        'expires_at': token.expires_at.isoformat(),
    }


def revoke(request, token: ApiToken) -> None:
    if token.revoked_at is not None:
        return
    token.revoked_at = timezone.now()
    token.revoked_by = request.user if request.user.is_authenticated else None
    token.save(update_fields=['revoked_at', 'revoked_by'])
    record(request, 'token.revoke', resource=token.prefix, details=snapshot(token))


def live_tokens(user):
    return ApiToken.objects.filter(user=user, revoked_at__isnull=True, expires_at__gt=timezone.now())
