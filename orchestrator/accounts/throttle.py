"""Sign-in throttling, per username and per client address.

Failures are counted from the audit log, so every orchestrator node sees the
same counts. A username's count restarts after a successful sign-in.
"""

from datetime import timedelta

from django.conf import settings
from django.utils import timezone

from audit.models import AuditLog

LOGIN = 'auth.login'


def locked_out(username: str, ip: str | None) -> bool:
    limit = settings.DEVICEVAULT_LOGIN_MAX_FAILURES
    since = timezone.now() - timedelta(minutes=settings.DEVICEVAULT_LOGIN_LOCKOUT_MIN)
    attempts = AuditLog.objects.filter(action=LOGIN, created_at__gte=since)
    failures = attempts.filter(outcome=AuditLog.FAILURE)

    last_success = (
        attempts.filter(outcome=AuditLog.SUCCESS, actor_name__iexact=username)
        .order_by('-created_at')
        .values_list('created_at', flat=True)
        .first()
    )
    by_name = failures.filter(actor_name__iexact=username)
    if last_success is not None:
        by_name = by_name.filter(created_at__gt=last_success)
    if by_name.count() >= limit:
        return True
    return ip is not None and failures.filter(ip=ip).count() >= limit
