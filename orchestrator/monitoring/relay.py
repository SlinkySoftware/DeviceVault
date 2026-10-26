"""The orchestrator's side of receiver monitoring relays (``devicevault_protocol.monitoring``).

Receivers learn the relay tokens (digests, never secrets) from their
assignment, which is re-sent when a relay token is created or revoked, when a
service account changes or is deleted, and when a relay token expires (the
scheduler leader notices; the relay also refuses an expired token itself).
Relays report back with signed ``monitoring.*`` events, handled here: token
use updates the token and audits a first use from a new address, refusals are
audited as ``token.refused`` naming the receiver, and a snapshot a relay could
not verify is logged and audited.
"""

import logging
from datetime import datetime, timedelta
from typing import Any

from django.db import transaction
from django.utils import timezone

from accounts import tokens
from accounts.models import ApiToken
from audit.log import record
from audit.models import AuditLog
from core.models import Worker
from devicevault_protocol import monitoring as protocol
from devicevault_protocol.push import normalise_address
from monitoring import snapshots
from push.events import EventRejected, receiver_event

logger = logging.getLogger('devicevault.monitoring')

# Monitoring events are worth little once old; they also expire in the queue.
EVENT_MAX_AGE = timedelta(hours=1)

_last_expiry_check: datetime | None = None

__all__ = ['EventRejected', 'expire_relay_tokens', 'handle_monitoring_event', 'relay_tokens_changed']


def relay_tokens_changed() -> None:
    """Relay tokens or their owners changed: new receiver assignments, and a publish at the next tick."""
    from push.service import receiver_inputs_changed

    receiver_inputs_changed()
    transaction.on_commit(snapshots.request_publish)


def expire_relay_tokens(now: datetime | None = None) -> bool:
    """The scheduler leader's hook: re-send receiver assignments once a relay token has expired.

    One indexed query a tick, covering expiries since the previous tick. Relays
    refuse an expired token on their own, so this only keeps assignments tidy.
    """
    global _last_expiry_check
    now = now or timezone.now()
    since, _last_expiry_check = _last_expiry_check, now
    if since is None:
        return False
    expired = ApiToken.objects.filter(
        revoked_at__isnull=True,
        expires_at__gt=since,
        expires_at__lte=now,
        user__profile__is_service_account=True,
    ).only('scopes')
    if not any(ApiToken.MONITORING in token.scopes for token in expired):
        return False
    relay_tokens_changed()
    return True


# --- events from relays --------------------------------------------------------------------


def handle_monitoring_event(envelope: Any) -> int:
    """Handle one signed ``monitoring.*`` event. Returns how many records it touched."""
    try:
        payload, worker = receiver_event(envelope, max_age=EVENT_MAX_AGE)
    except EventRejected as exc:
        logger.warning('monitoring_event_rejected', extra={'reason': str(exc)})
        raise
    event = payload.get('event')
    if event == protocol.EVENT_USED:
        return _used(payload, worker)
    if event == protocol.EVENT_REFUSED:
        return _refused(payload, worker)
    if event == protocol.EVENT_SNAPSHOT_REJECTED:
        return _snapshot_rejected(payload, worker)
    logger.warning('monitoring_event_unknown', extra={'event': event, 'receiver': worker.name})
    return 0


def _address(value: Any) -> str | None:
    try:
        return normalise_address(str(value))
    except ValueError:
        return None


def _timestamp(value: Any) -> datetime:
    try:
        at = datetime.fromisoformat(str(value))
    except ValueError:
        return timezone.now()
    return min(at, timezone.now()) if timezone.is_aware(at) else timezone.now()


def _used(payload: dict[str, Any], worker: Worker) -> int:
    entries = [e for e in payload.get('tokens') or [] if isinstance(e, dict)][: protocol.MAX_REPORTED_TOKENS]
    touched = 0
    for entry in entries:
        token = (
            ApiToken.objects.select_related('user')
            .filter(prefix=str(entry.get('prefix') or '')[: tokens.PREFIX_LENGTH])
            .first()
        )
        if token is None or not tokens.is_relay_token(token):
            logger.warning('monitoring_use_unknown_token', extra={'receiver': worker.name})
            continue
        addresses = [a for a in map(_address, entry.get('addresses') or []) if a]
        at = _timestamp(entry.get('last_used_at') or payload.get('at'))
        for address in addresses[: protocol.MAX_REPORTED_ADDRESSES] or [None]:
            tokens.touch(None, token, address, receiver=worker.name, at=at)
        touched += 1
    return touched


def _refused(payload: dict[str, Any], worker: Worker) -> int:
    cause = payload.get('cause')
    prefix = str(payload.get('prefix') or '')[: tokens.PREFIX_LENGTH]
    tokens.refused(
        None,
        prefix,
        cause if cause in protocol.REFUSAL_CAUSES else protocol.CAUSE_UNKNOWN,
        _address(payload.get('source_ip')),
        receiver=worker.name,
    )
    return 1


def _snapshot_rejected(payload: dict[str, Any], worker: Worker) -> int:
    details = {
        'receiver': worker.name,
        'owner': payload.get('owner') if isinstance(payload.get('owner'), int) else None,
        'generation': str(payload.get('generation') or '')[:64],
        'reason': str(payload.get('reason') or '')[:255],
    }
    logger.error('monitoring_snapshot_rejected', extra=details)
    record(
        None,
        'monitoring.snapshot_rejected',
        resource=worker.name,
        outcome=AuditLog.FAILURE,
        details=details,
        actor_name=worker.name,
    )
    return 1
