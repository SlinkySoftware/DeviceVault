"""API for backup jobs: history, content, logs, pins and labels. The dashboard is in backups.dashboard."""

from django.core.exceptions import ValidationError as DjangoValidationError
from django.db import transaction
from django.http import HttpResponse
from django.utils import timezone
from rest_framework import decorators, response, serializers, status, viewsets
from rest_framework.exceptions import PermissionDenied
from rest_framework.pagination import PageNumberPagination

from accounts import access
from accounts.access import HasDeviceGroupPermission
from audit.log import record
from backups.content import ContentDeleted, ContentUnavailable, read_content
from backups.models import LABEL_MAX, NOTE_MAX, BackupJob


class BackupJobSerializer(serializers.ModelSerializer):
    device_name = serializers.CharField(source='device.name', read_only=True)
    requested_by_username = serializers.CharField(source='requested_by.username', read_only=True, default=None)
    storage_target_name = serializers.CharField(source='storage_target.name', read_only=True, default=None)
    duration_ms = serializers.IntegerField(read_only=True)
    pruned = serializers.BooleanField(read_only=True)
    pinned_by_username = serializers.CharField(source='pinned_by.username', read_only=True, default=None)
    annotated_by_username = serializers.CharField(source='annotated_by.username', read_only=True, default=None)

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
            'pinned_by_username',
            'pinned_at',
            'label',
            'note',
            'annotated_by_username',
            'annotated_at',
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


class PinSerializer(serializers.Serializer):
    pinned = serializers.BooleanField()


class AnnotationSerializer(serializers.Serializer):
    """Either field may be left out to keep it; blank clears it."""

    label = serializers.CharField(max_length=LABEL_MAX, allow_blank=True, required=False)
    note = serializers.CharField(max_length=NOTE_MAX, allow_blank=True, required=False, trim_whitespace=False)

    def validate_label(self, value):
        if '\n' in value or '\r' in value:
            raise serializers.ValidationError('A label is a single line.')
        return value

    def validate_note(self, value):
        return value.strip()


class JobPagination(PageNumberPagination):
    page_size = 50
    page_size_query_param = 'page_size'
    max_page_size = 500


class BackupJobViewSet(viewsets.ReadOnlyModelViewSet):
    """Backup jobs of the devices the user can view (``view``: state, history, sizes, errors and logs).

    Paginated (``?page=``, ``?page_size=``). Filters: ``?device=<id>``, ``?state=<state>``,
    ``?changed=true|false`` (the change summary; see backups.changes), ``?pinned=true|false`` and
    ``?labelled=true|false``. ``{id}/pin/`` (``admin``: it overrides the group's retention policy) and
    ``{id}/annotate/`` (``view_contents``: a label describes the content) change them. The backups
    themselves: ``{id}/content/`` (``view_contents``), ``{id}/download/`` (``download``) and
    ``compare/?a=<id>&b=<id>`` (``view_contents``, two backups of one device). Each is audited.
    """

    serializer_class = BackupJobSerializer
    permission_classes = [HasDeviceGroupPermission('view')]
    pagination_class = JobPagination

    def get_queryset(self):
        jobs = BackupJob.objects.select_related('device', 'requested_by', 'storage_target', 'pinned_by', 'annotated_by')
        jobs = jobs.filter(device__in=access.devices_for(self.request.user, 'view'))
        params = self.request.query_params
        if params.get('device'):
            jobs = jobs.filter(device_id=params['device'])
        if params.get('state'):
            jobs = jobs.filter(state=params['state'])
        if params.get('changed') in ('true', 'false'):
            jobs = jobs.filter(changed=params['changed'] == 'true')
        if params.get('pinned') in ('true', 'false'):
            jobs = jobs.filter(pinned=params['pinned'] == 'true')
        if params.get('labelled') in ('true', 'false'):
            jobs = jobs.exclude(label='') if params['labelled'] == 'true' else jobs.filter(label='')
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

    @decorators.action(detail=True, methods=['post'], permission_classes=[HasDeviceGroupPermission('admin')])
    def pin(self, request, pk=None):
        """Pin a stored backup (retention leaves it alone) or unpin it (it rejoins its policy)."""
        job = self.get_object()
        body = PinSerializer(data=request.data)
        body.is_valid(raise_exception=True)
        pinned = body.validated_data['pinned']
        # Retention claims deletions under the same row lock and re-checks ``pinned``,
        # so a backup is never both pinned and deleted.
        with transaction.atomic():
            job = BackupJob.objects.select_for_update().get(pk=job.pk)
            if pinned and not job.pinned:
                if job.state != BackupJob.STORED:
                    return response.Response(
                        {'error': 'Only a stored backup can be pinned.'}, status=status.HTTP_400_BAD_REQUEST
                    )
                if job.pruned:
                    return response.Response(
                        {'error': 'Its retention policy has already deleted this backup.'},
                        status=status.HTTP_400_BAD_REQUEST,
                    )
                if job.device.purge_requested_at:
                    return response.Response(
                        {'error': "This device's backups are being purged."}, status=status.HTTP_400_BAD_REQUEST
                    )
                job.pinned, job.pinned_by, job.pinned_at = True, request.user, timezone.now()
            elif not pinned and job.pinned:
                job.pinned, job.pinned_by, job.pinned_at = False, None, None
            else:
                return response.Response(BackupJobSerializer(self.get_object()).data)
            job.save(update_fields=['pinned', 'pinned_by', 'pinned_at'])
        self._audit('backup.pin' if pinned else 'backup.unpin', job, label=job.label)
        return response.Response(BackupJobSerializer(self.get_object()).data)

    @decorators.action(detail=True, methods=['post'], permission_classes=[HasDeviceGroupPermission('view_contents')])
    def annotate(self, request, pk=None):
        """Set a finished backup's label and note."""
        job = self.get_object()
        if job.state not in BackupJob.TERMINAL_STATES:
            return response.Response(
                {'error': 'Wait for the backup to finish before labelling it.'}, status=status.HTTP_400_BAD_REQUEST
            )
        body = AnnotationSerializer(data=request.data)
        body.is_valid(raise_exception=True)
        label = body.validated_data.get('label', job.label)
        note = body.validated_data.get('note', job.note)
        if (label, note) != (job.label, job.note):
            note_changed = note != job.note
            BackupJob.objects.filter(pk=job.pk).update(
                label=label, note=note, annotated_by=request.user, annotated_at=timezone.now()
            )
            # The note is free text up to NOTE_MAX characters: the audit log says only that it changed.
            self._audit('backup.annotate', job, label=label, note_changed=note_changed)
        return response.Response(BackupJobSerializer(self.get_object()).data)


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
