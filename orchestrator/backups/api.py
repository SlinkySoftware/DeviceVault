"""API for backup jobs: history, content, logs, dashboard statistics and activity."""

from datetime import timedelta

from django.db.models import Avg, Count, DurationField, ExpressionWrapper, F, Q
from django.http import HttpResponse
from django.utils import timezone
from rest_framework import decorators, response, serializers, status, viewsets
from rest_framework.exceptions import PermissionDenied
from rest_framework.pagination import PageNumberPagination
from rest_framework.permissions import IsAuthenticated

from backups.content import ContentUnavailable, read_content
from backups.models import BackupJob
from core.timezone_utils import get_day_bounds_local, get_timezone_name, local_now
from devices.models import Device, DeviceGroup
from devices.permissions import user_get_accessible_device_groups, user_get_device_group_django_permissions


def groups_with(user, permission: str):
    """Device groups in which ``user`` has the given device-group permission."""
    if user.is_staff or user.is_superuser:
        return DeviceGroup.objects.all()
    ids = [g.pk for g in DeviceGroup.objects.all() if permission in user_get_device_group_django_permissions(user, g)]
    return DeviceGroup.objects.filter(pk__in=ids)


class BackupJobSerializer(serializers.ModelSerializer):
    device_name = serializers.CharField(source='device.name', read_only=True)
    requested_by_username = serializers.CharField(source='requested_by.username', read_only=True, default=None)
    location_name = serializers.CharField(source='location.name', read_only=True, default=None)
    duration_ms = serializers.IntegerField(read_only=True)

    class Meta:
        model = BackupJob
        fields = [
            'id',
            'device',
            'device_name',
            'state',
            'trigger',
            'requested_by_username',
            'driver',
            'is_binary',
            'encrypted',
            'size_bytes',
            'storage_backend',
            'location_name',
            'collector',
            'storage_worker',
            'attempts',
            'error',
            'created_at',
            'started_at',
            'collected_at',
            'finished_at',
            'collect_duration_ms',
            'store_duration_ms',
            'duration_ms',
        ]
        read_only_fields = fields


class JobPagination(PageNumberPagination):
    page_size = 50
    page_size_query_param = 'page_size'
    max_page_size = 500


class BackupJobViewSet(viewsets.ReadOnlyModelViewSet):
    """Backup jobs of devices the user may view backups of.

    Paginated (``?page=``, ``?page_size=``). Filters: ``?device=<id>``, ``?state=<state>``. Actions: ``content`` (the
    backup itself) and ``logs``.
    """

    serializer_class = BackupJobSerializer
    permission_classes = [IsAuthenticated]
    pagination_class = JobPagination

    def get_queryset(self):
        jobs = BackupJob.objects.select_related('device', 'requested_by', 'location').filter(
            device__device_group__in=groups_with(self.request.user, 'view_backups')
        )
        params = self.request.query_params
        if params.get('device'):
            jobs = jobs.filter(device_id=params['device'])
        if params.get('state'):
            jobs = jobs.filter(state=params['state'])
        return jobs

    @decorators.action(detail=True, methods=['get'])
    def content(self, request, pk=None):
        job = self.get_object()
        try:
            data = read_content(job)
        except ContentUnavailable as exc:
            return response.Response({'error': str(exc)}, status=status.HTTP_502_BAD_GATEWAY)
        filename = f'{job.device.name}-{job.created_at:%Y%m%d-%H%M%S}{".bin" if job.is_binary else ".cfg"}'
        content_type = 'application/octet-stream' if job.is_binary else 'text/plain; charset=utf-8'
        reply = HttpResponse(data, content_type=content_type)
        reply['Content-Disposition'] = f'attachment; filename="{filename}"'
        return reply

    @decorators.action(detail=True, methods=['get'])
    def logs(self, request, pk=None):
        return response.Response({'logs': self.get_object().log})


def device_backup_now(request, device) -> response.Response:
    """POST /api/devices/{id}/backup_now/: queue a backup (or return the one already running)."""
    from backups.jobs import JobError, create_job

    if not (request.user.is_staff or request.user.is_superuser):
        if not device.device_group or 'backup_now' not in user_get_device_group_django_permissions(
            request.user, device.device_group
        ):
            raise PermissionDenied('You may not start backups of devices in this group')
    try:
        job, created = create_job(device, user=request.user)
    except JobError as exc:
        return response.Response({'error': str(exc)}, status=status.HTTP_400_BAD_REQUEST)
    return response.Response(
        {'job': BackupJobSerializer(job).data, 'created': created},
        status=status.HTTP_202_ACCEPTED if created else status.HTTP_200_OK,
    )


FAILED_STATES = (BackupJob.FAILED, BackupJob.TIMED_OUT)
ACTIVITY_WINDOWS = {'1h': timedelta(hours=1), '24h': timedelta(hours=24), '7d': timedelta(days=7)}


@decorators.api_view(['GET'])
def dashboard_stats(request):
    days = min(max(int(request.GET.get('days', 7)), 1), 90)
    now = timezone.now()
    since = now - timedelta(hours=24)
    devices = Device.objects.filter(device_group__in=user_get_accessible_device_groups(request.user))
    jobs = BackupJob.objects.filter(device__in=devices)
    recent = jobs.filter(finished_at__gte=since)

    by_type = devices.values('device_type__name', 'device_type__icon').annotate(count=Count('id'))
    duration = ExpressionWrapper(F('finished_at') - F('created_at'), output_field=DurationField())
    average = recent.filter(state=BackupJob.STORED).annotate(d=duration).aggregate(avg=Avg('d'))['avg']
    with_status = devices.exclude(last_backup_status='')
    healthy = with_status.filter(last_backup_status='success').count()

    daily = []
    today = local_now().date()
    for offset in range(days - 1, -1, -1):
        day = today - timedelta(days=offset)
        start, end = get_day_bounds_local(day)
        counts = jobs.filter(finished_at__gte=start, finished_at__lt=end).aggregate(
            success=Count('id', filter=Q(state=BackupJob.STORED)),
            failed=Count('id', filter=Q(state__in=FAILED_STATES)),
        )
        total = counts['success'] + counts['failed']
        daily.append(
            {
                'date': day.isoformat(),
                'success': counts['success'],
                'failed': counts['failed'],
                'rate': counts['success'] / total * 100 if total else 0,
            }
        )

    return response.Response(
        {
            'devicesByType': {
                row['device_type__name']: {'count': row['count'], 'icon': row['device_type__icon']} for row in by_type
            },
            'success24h': recent.filter(state=BackupJob.STORED).count(),
            'failed24h': recent.filter(state__in=FAILED_STATES).count(),
            'inProgress24h': jobs.filter(state__in=BackupJob.ACTIVE_STATES).count(),
            'avgDuration': round(average.total_seconds(), 1) if average else 0.0,
            # Devices whose latest finished backup succeeded, of those backed up at all.
            'successRate': round(healthy / with_status.count() * 100, 1) if with_status.exists() else 0,
            'dailyStats': daily,
            'timezone': get_timezone_name(),
        }
    )


@decorators.api_view(['GET'])
def recent_backup_activity(request):
    window = ACTIVITY_WINDOWS.get(request.GET.get('time_filter', '1h'), ACTIVITY_WINDOWS['1h'])
    devices = Device.objects.filter(device_group__in=user_get_accessible_device_groups(request.user))
    jobs = (
        BackupJob.objects.filter(device__in=devices, created_at__gte=timezone.now() - window)
        .select_related('device')
        .order_by('-created_at')[:200]
    )
    return response.Response(
        [
            {
                'id': str(job.id),
                'device_id': job.device_id,
                'device_name': job.device.name,
                'state': job.state,
                'trigger': job.trigger,
                'created_at': job.created_at,
                'finished_at': job.finished_at,
                'duration_ms': job.duration_ms,
                'error': job.error,
                'has_log': bool(job.log),
            }
            for job in jobs
        ]
    )
