"""Recording audit events."""

import ipaddress
import logging

from audit.models import AuditLog

logger = logging.getLogger('devicevault.audit')


def client_ip(request) -> str | None:
    """The client's address: the last X-Forwarded-For hop (added by our nginx), else the peer."""
    forwarded = request.META.get('HTTP_X_FORWARDED_FOR', '')
    address = forwarded.split(',')[-1].strip() if forwarded else request.META.get('REMOTE_ADDR', '')
    try:
        return str(ipaddress.ip_address(address))
    except ValueError:
        return None


def _token_prefix(request) -> str:
    """The prefix of the API token the request authenticated with, if any."""
    from accounts.models import ApiToken

    auth = getattr(request, '_auth', None) if request is not None else None
    return auth.prefix if isinstance(auth, ApiToken) else ''


def record(
    request,
    action: str,
    resource: str = '',
    *,
    outcome: str = AuditLog.SUCCESS,
    details: dict | None = None,
    device_group=None,
    actor=None,
    actor_name: str | None = None,
) -> AuditLog:
    """Record ``action`` by the request's user (or ``actor``), with where it came from.

    ``request`` may be None for actions with no HTTP request behind them.
    """
    if actor is None and request is not None:
        user = getattr(request, 'user', None)
        actor = user if user is not None and user.is_authenticated else None
    if actor_name is None:
        actor_name = actor.get_username() if actor is not None else ''
    prefix = _token_prefix(request)
    if prefix:
        details = {**(details or {}), 'token': prefix}
    entry = AuditLog.objects.create(
        actor=actor,
        actor_name=actor_name[:150],
        action=action,
        resource=str(resource)[:128],
        outcome=outcome,
        details=details or {},
        ip=client_ip(request) if request is not None else None,
        user_agent=(request.META.get('HTTP_USER_AGENT', '') if request is not None else '')[:512],
        device_group_id=getattr(device_group, 'pk', device_group),
    )
    logger.info('audit', extra={'action': action, 'outcome': outcome, 'actor': actor_name, 'resource': resource})
    return entry
