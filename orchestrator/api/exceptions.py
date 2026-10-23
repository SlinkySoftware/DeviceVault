"""API error handling: refused requests are audited."""

from rest_framework import status
from rest_framework.views import exception_handler as drf_exception_handler

from audit.log import record
from audit.models import AuditLog


def exception_handler(exc, context):
    reply = drf_exception_handler(exc, context)
    request = context.get('request')
    if reply is not None and reply.status_code == status.HTTP_403_FORBIDDEN and request is not None:
        if request.user.is_authenticated:
            record(
                request,
                'access.denied',
                resource=request.path,
                outcome=AuditLog.DENIED,
                details={'method': request.method, 'reason': str(getattr(exc, 'detail', ''))},
            )
    return reply
