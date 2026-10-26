"""Caching the monitoring figures, and publishing the device snapshots relays serve.

Estate, group and platform sections are computed when asked and cached in Redis
per owner and scope set for ``DV_MONITORING_CACHE_SECONDS``; a lock makes one node
compute while the others serve the previous value (or wait briefly when there is
none). Device figures are instead published by the scheduler leader every
``DV_MONITORING_PUBLISH_SECONDS``, one signed snapshot per relay owner (a service
account with a live ``monitoring`` token), for the receivers' relays and the
orchestrator's own ``device/`` endpoint (``devicevault_protocol.monitoring``).
"""

import json
import logging
import time
from collections.abc import Callable
from datetime import datetime, timedelta

from django.conf import settings
from django.contrib.auth.models import User
from django.utils import timezone
from redis import Redis
from redis.exceptions import RedisError

from accounts import access
from accounts.models import ApiToken
from core.signing import signing_key
from devicevault_protocol import monitoring as protocol
from monitoring import metrics

logger = logging.getLogger('devicevault.monitoring')

LOCK_SECONDS = 30
WAIT_SECONDS = 5
PUBLISH_NOW_KEY = 'dv:monitoring:publish-now'
_last_publish: datetime | None = None


def _redis() -> Redis:
    return Redis.from_url(settings.DEVICEVAULT_BUS.redis_url, socket_connect_timeout=2, socket_timeout=5)


def cached(owner, scopes: str, section: str, compute: Callable[[], object]):
    """``compute()``'s result for ``owner``, from the cache while it is fresh."""
    key = f'dv:monitoring:{owner.pk}:{scopes}:{section}'
    lifetime = settings.DEVICEVAULT_MONITORING_CACHE_SECONDS
    try:
        redis = _redis()
        raw = redis.get(key)
        if raw is not None and _fresh(raw, lifetime):
            return json.loads(raw)['value']
        if not redis.set(f'{key}:lock', 1, nx=True, ex=LOCK_SECONDS):
            if raw is not None:
                return json.loads(raw)['value']  # another node is refreshing it
            deadline = time.monotonic() + WAIT_SECONDS
            while time.monotonic() < deadline:
                time.sleep(0.2)
                raw = redis.get(key)
                if raw is not None and _fresh(raw, lifetime):
                    return json.loads(raw)['value']
        try:
            value = compute()
            # Kept past its lifetime, so it can be served while a refresh runs.
            redis.set(key, json.dumps({'at': time.time(), 'value': value}, default=str), ex=lifetime * 10)
        finally:
            redis.delete(f'{key}:lock')
        return value
    except RedisError as exc:
        logger.warning('monitoring_cache_unavailable', extra={'error': str(exc)})
        return compute()


def _fresh(raw: bytes, lifetime: int) -> bool:
    try:
        return time.time() - json.loads(raw)['at'] < lifetime
    except ValueError, KeyError, TypeError:
        return False


# --- relay snapshots -----------------------------------------------------------------------


def relay_tokens(now: datetime | None = None) -> list[ApiToken]:
    """Live tokens with the monitoring scope of active service accounts: the tokens relays accept."""
    tokens = (
        ApiToken.objects.filter(
            revoked_at__isnull=True,
            expires_at__gt=now or timezone.now(),
            user__is_active=True,
            user__profile__is_service_account=True,
        )
        .select_related('user')
        .order_by('prefix')
    )
    return [token for token in tokens if ApiToken.MONITORING in token.scopes]


def relay_owners() -> list[User]:
    """Service accounts holding a live token with the monitoring scope."""
    owners = {token.user.pk: token.user for token in relay_tokens()}
    return [owners[pk] for pk in sorted(owners)]


def publish_relays(now: datetime | None = None) -> int:
    """Publish every relay owner's device snapshot. Returns how many were published."""
    now = now or timezone.now()
    redis = _redis()
    published = 0
    for owner in relay_owners():
        rows, by_ip = metrics.device_rows(access.devices_for(owner, 'view'), now)
        protocol.publish(
            redis,
            signing_key(),
            owner.pk,
            rows,
            by_ip,
            interval=settings.DEVICEVAULT_MONITORING_PUBLISH_SECONDS,
            now=now,
        )
        published += 1
    return published


def request_publish() -> None:
    """Have the scheduler leader publish at its next tick (relay owners or their grants changed)."""
    try:
        _redis().set(PUBLISH_NOW_KEY, 1, ex=settings.DEVICEVAULT_MONITORING_PUBLISH_SECONDS)
    except RedisError as exc:  # the next interval publishes anyway
        logger.warning('monitoring_publish_request_failed', extra={'error': str(exc)})


def publish_if_due(now: datetime | None = None) -> int | None:
    """The scheduler leader's hook: publish when the interval has passed, at start-up, and when asked."""
    global _last_publish
    now = now or timezone.now()
    interval = timedelta(seconds=settings.DEVICEVAULT_MONITORING_PUBLISH_SECONDS)
    try:
        redis = _redis()
        if _last_publish is not None and now - _last_publish < interval and not redis.delete(PUBLISH_NOW_KEY):
            return None
        _last_publish = now
        return publish_relays(now)
    except RedisError as exc:
        logger.warning('monitoring_publish_failed', extra={'error': str(exc)})
        return None


def owner_snapshot(owner) -> protocol.Snapshot | None:
    """``owner``'s published snapshot, verified as a relay would verify it."""
    return protocol.load(_redis(), owner.pk, signing_key().public_key())
