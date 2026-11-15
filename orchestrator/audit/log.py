"""Recording audit events."""

import ipaddress
import logging

from django.conf import settings

from audit.models import AuditLog

logger = logging.getLogger('devicevault.audit')


def client_ip(request) -> str | None:
    """The client's address, from X-Forwarded-For (our nginx appends the peer it saw), else the peer.

    Read from the right, skipping ``DV_TRUSTED_PROXIES`` (a TLS proxy or load balancer in front of
    nginx): the first hop that is not one of them is the client, since everything to its left is
    whatever the client chose to send. With no trusted proxies that is the hop nginx added.
    """
    forwarded = request.META.get('HTTP_X_FORWARDED_FOR', '')
    hops = [hop.strip() for hop in forwarded.split(',')] if forwarded else [request.META.get('REMOTE_ADDR', '')]
    address = None
    for hop in reversed(hops):
        try:
            address = ipaddress.ip_address(hop)
        except ValueError:
            return None  # a hop a trusted proxy would never write: nothing left of here can be believed
        if address.version == 6 and address.ipv4_mapped:
            address = address.ipv4_mapped
        if not any(address in network for network in settings.DEVICEVAULT_TRUSTED_PROXIES):
            break
    # Every hop a trusted proxy: the request came from the outermost one itself.
    return str(address) if address is not None else None


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
