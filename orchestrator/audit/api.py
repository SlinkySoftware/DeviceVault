"""API for reading the audit log (global administrators only)."""

from django.utils.dateparse import parse_datetime
from rest_framework import serializers, viewsets
from rest_framework.pagination import PageNumberPagination

from accounts.access import IsGlobalAdmin
from audit.models import AuditLog


class AuditLogSerializer(serializers.ModelSerializer):
    device_group_name = serializers.CharField(source='device_group.name', read_only=True, default=None)

    class Meta:
        model = AuditLog
        fields = [
            'id',
            'created_at',
            'actor',
            'actor_name',
            'action',
            'resource',
            'outcome',
            'details',
            'ip',
            'user_agent',
            'device_group',
            'device_group_name',
        ]
        read_only_fields = fields


class AuditPagination(PageNumberPagination):
    page_size = 50
    page_size_query_param = 'page_size'
    max_page_size = 500


class AuditLogViewSet(viewsets.ReadOnlyModelViewSet):
    """The audit log, newest first.

    Filters: ``?action=`` (prefix, e.g. ``auth.``), ``?outcome=``, ``?actor=`` (name contains),
    ``?device_group=<id>``, ``?since=`` and ``?until=`` (ISO 8601), ``?search=`` (resource contains).
    """

    serializer_class = AuditLogSerializer
    permission_classes = [IsGlobalAdmin]
    pagination_class = AuditPagination

    def get_queryset(self):
        entries = AuditLog.objects.select_related('device_group')
        params = self.request.query_params
        if params.get('action'):
            entries = entries.filter(action__startswith=params['action'])
        if params.get('outcome'):
            entries = entries.filter(outcome=params['outcome'])
        if params.get('actor'):
            entries = entries.filter(actor_name__icontains=params['actor'])
        if params.get('device_group'):
            entries = entries.filter(device_group_id=params['device_group'])
        if params.get('search'):
            entries = entries.filter(resource__icontains=params['search'])
        for param, lookup in (('since', 'created_at__gte'), ('until', 'created_at__lte')):
            when = parse_datetime(params.get(param, ''))
            if when is not None:
                entries = entries.filter(**{lookup: when})
        return entries
