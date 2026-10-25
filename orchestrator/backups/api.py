"""API for backup jobs: history, content, logs, dashboard statistics and activity."""

from datetime import timedelta

from django.core.exceptions import ValidationError as DjangoValidationError
from django.db.models import Avg, Count, DurationField, ExpressionWrapper, F, Q
from django.http import HttpResponse
from django.utils import timezone
from rest_framework import decorators, response, serializers, status, viewsets
from rest_framework.exceptions import PermissionDenied
from rest_framework.pagination import PageNumberPagination
from rest_framework.permissions import IsAuthenticated

from accounts import access
from accounts.access import HasDeviceGroupPermission
from audit.log import record
from backups.content import ContentDeleted, ContentUnavailable, read_content
from backups.models import BackupJob
from core.timezone_utils import get_day_bounds_local, get_timezone_name, local_now
from devices.models import Device


class BackupJobSerializer(serializers.ModelSerializer):
    device_name = serializers.CharField(source='device.name', read_only=True)
    requested_by_username = serializers.CharField(source='requested_by.username', read_only=True, default=None)
    storage_target_name = serializers.CharField(source='storage_target.name', read_only=True, default=None)
    duration_ms = serializers.IntegerField(read_only=True)
    pruned = serializers.BooleanField(read_only=True)

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
            'source_filename',
            'is_binary',
            'encrypted',
            'size_bytes',
            'storage_driver',
            'storage_target',
            'storage_target_name',
            'collector',
            'storage_worker',
            'pinned',
            'pruned',
            'pruned_at',
            'changed',
            'lines_added',
            'lines_removed',
            'compared_to',
            'summary_error',
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


def _unavailable(exc: ContentUnavailable) -> response.Response:
    """410 for a backup retention deleted, 502 when storage could not provide it."""
    code = status.HTTP_410_GONE if isinstance(exc, ContentDeleted) else status.HTTP_502_BAD_GATEWAY
    return response.Response({'error': str(exc)}, status=code)


class JobPagination(PageNumberPagination):
    page_size = 50
    page_size_query_param = 'page_size'
    max_page_size = 500


class BackupJobViewSet(viewsets.ReadOnlyModelViewSet):
    """Backup jobs of the devices the user can view (``view``: state, history, sizes, errors and logs).

    Paginated (``?page=``, ``?page_size=``). Filters: ``?device=<id>``, ``?state=<state>``,
    ``?changed=true|false`` (the change summary; see backups.changes). The backups
    themselves: ``{id}/content/`` (``view_contents``), ``{id}/download/`` (``download``) and
    ``compare/?a=<id>&b=<id>`` (``view_contents``, two backups of one device). Each is audited.
    """

    serializer_class = BackupJobSerializer
    permission_classes = [HasDeviceGroupPermission('view')]
    pagination_class = JobPagination

    def get_queryset(self):
        jobs = BackupJob.objects.select_related('device', 'requested_by', 'storage_target')
        jobs = jobs.filter(device__in=access.devices_for(self.request.user, 'view'))
        params = self.request.query_params
        if params.get('device'):
            jobs = jobs.filter(device_id=params['device'])
        if params.get('state'):
            jobs = jobs.filter(state=params['state'])
        if params.get('changed') in ('true', 'false'):
            jobs = jobs.filter(changed=params['changed'] == 'true')
        return jobs

    def _audit(self, action: str, job: BackupJob, **details):
        record(
            self.request,
            action,
            resource=str(job.id),
            device_group=job.device.device_group_id,
            details={'device': job.device_id, 'device_name': job.device.name, 'job': str(job.id), **details},
        )

    def _content(self, job: BackupJob, *, attachment: bool):
        try:
            data = read_content(job)
        except ContentUnavailable as exc:
            return _unavailable(exc)
        content_type = 'application/octet-stream' if job.is_binary else 'text/plain; charset=utf-8'
        reply = HttpResponse(data, content_type=content_type)
        if attachment:
            filename = f'{job.device.name}-{job.created_at:%Y%m%d-%H%M%S}{".bin" if job.is_binary else ".cfg"}'
            reply['Content-Disposition'] = f'attachment; filename="{filename}"'
        return reply

    @decorators.action(detail=True, methods=['get'], permission_classes=[HasDeviceGroupPermission('view_contents')])
    def content(self, request, pk=None):
        job = self.get_object()
        self._audit('backup.view', job)
        return self._content(job, attachment=False)

    @decorators.action(detail=True, methods=['get'], permission_classes=[HasDeviceGroupPermission('download')])
    def download(self, request, pk=None):
        job = self.get_object()
        self._audit('backup.download', job)
        return self._content(job, attachment=True)

    @decorators.action(detail=False, methods=['get'], permission_classes=[HasDeviceGroupPermission('view_contents')])
    def compare(self, request):
        jobs = self.get_queryset()
        ids = [request.query_params.get('a'), request.query_params.get('b')]
        try:
            pair = [jobs.get(pk=job_id) for job_id in ids]
        except BackupJob.DoesNotExist, ValueError, DjangoValidationError:
            return response.Response({'error': 'Choose two backups to compare.'}, status=status.HTTP_404_NOT_FOUND)
        if pair[0].device_id != pair[1].device_id:
            return response.Response(
                {'error': 'Only backups of the same device can be compared.'}, status=status.HTTP_400_BAD_REQUEST
            )
        for job in pair:
            self.check_object_permissions(request, job)
        try:
            contents = [read_content(job) for job in pair]
        except ContentUnavailable as exc:
            return _unavailable(exc)
        self._audit('backup.diff', pair[0], other_job=str(pair[1].id))
        return response.Response(
            {
                'a': {'job': BackupJobSerializer(pair[0]).data, 'content': contents[0].decode('utf-8', 'replace')},
                'b': {'job': BackupJobSerializer(pair[1]).data, 'content': contents[1].decode('utf-8', 'replace')},
            }
        )

    @decorators.action(detail=True, methods=['get'])
    def logs(self, request, pk=None):
        return response.Response({'logs': self.get_object().log})


def device_backup_now(request, device) -> response.Response:
    """POST /api/devices/{id}/backup_now/: queue a backup (or return the one already running)."""
    from backups.jobs import JobError, create_job

    if not access.can(request.user, 'backup_now', device.device_group_id):
        raise PermissionDenied('You may not start backups of devices in this group')
    try:
        job, created = create_job(device, user=request.user)
    except JobError as exc:
        return response.Response({'error': str(exc)}, status=status.HTTP_400_BAD_REQUEST)
    record(
        request,
        'backup.start',
        resource=str(job.id),
        device_group=device.device_group_id,
        details={'device': device.pk, 'device_name': device.name, 'job': str(job.id), 'created': created},
    )
    return response.Response(
        {'job': BackupJobSerializer(job).data, 'created': created},
        status=status.HTTP_202_ACCEPTED if created else status.HTTP_200_OK,
    )


FAILED_STATES = (BackupJob.FAILED, BackupJob.TIMED_OUT)
ACTIVITY_WINDOWS = {'1h': timedelta(hours=1), '24h': timedelta(hours=24), '7d': timedelta(days=7)}


@decorators.api_view(['GET'])
@decorators.permission_classes([IsAuthenticated])
def dashboard_stats(request):
    days = min(max(int(request.GET.get('days', 7)), 1), 90)
    now = timezone.now()
    since = now - timedelta(hours=24)
    devices = access.devices_for(request.user, 'view', Device.objects.all())
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
@decorators.permission_classes([IsAuthenticated])
def recent_backup_activity(request):
    window = ACTIVITY_WINDOWS.get(request.GET.get('time_filter', '1h'), ACTIVITY_WINDOWS['1h'])
    devices = access.devices_for(request.user, 'view', Device.objects.all())
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
