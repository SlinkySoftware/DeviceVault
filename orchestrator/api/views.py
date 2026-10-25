"""
DeviceVault - A comprehensive network device backup management application with web interface for user and admin access and backend component for automated backup collection.
Copyright (C) 2026, Slinky Software

This program is free software: you can redistribute it and/or modify
it under the terms of the GNU General Public License as published by
the Free Software Foundation, either version 3 of the License, or
 (at your option) any later version.

This program is distributed in the hope that it will be useful,
but WITHOUT ANY WARRANTY; without even the implied warranty of
MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
GNU General Public License for more details.

You should have received a copy of the GNU General Public License
along with this program.  If not, see <http://www.gnu.org/licenses/>.
"""

from django.conf import settings
from django.db.models import ProtectedError
from rest_framework import decorators, mixins, response, serializers, status, viewsets
from rest_framework.exceptions import NotFound, PermissionDenied, ValidationError
from rest_framework.permissions import AllowAny, IsAuthenticated
from rest_framework.views import APIView

from accounts import access
from accounts.access import HasDeviceGroupPermission, IsGlobalAdmin, IsGlobalAdminOrReadOnly
from audit.log import record
from backups.api import device_backup_now
from core import workers as worker_registry
from core.models import UserProfile, Worker
from core.workers import driver_catalogue
from credentials.models import Credential, CredentialType
from devices import lifecycle
from devices.models import CollectionGroup, Device, DeviceType, Manufacturer
from devicevault_protocol.registration import ROLE_COLLECTOR, ROLE_RECEIVER, ROLE_STORAGE, STATUS_APPROVED
from policies.models import BackupSchedule, RetentionPolicy

from .serializers import (
    BackupScheduleSerializer,
    CollectionGroupSerializer,
    CredentialSerializer,
    CredentialTypeSerializer,
    DeviceDetailedSerializer,
    DeviceGroupSerializer,
    DeviceSerializer,
    DeviceTypeSerializer,
    DeviceWriteSerializer,
    ManufacturerSerializer,
    RetentionPolicySerializer,
    SummarySerializer,
    UserProfileSerializer,
    WorkerApprovalSerializer,
    WorkerSerializer,
)


def protected_conflict(exc: ProtectedError, noun: str) -> response.Response:
    kinds = sorted({str(obj._meta.verbose_name_plural) for obj in exc.protected_objects})
    return response.Response(
        {'error': f'This {noun} is still used by {", ".join(kinds)}.'}, status=status.HTTP_409_CONFLICT
    )


class DeviceTypeViewSet(viewsets.ModelViewSet):
    queryset = DeviceType.objects.all()
    permission_classes = [IsGlobalAdminOrReadOnly]
    serializer_class = DeviceTypeSerializer


class ManufacturerViewSet(viewsets.ModelViewSet):
    queryset = Manufacturer.objects.all()
    permission_classes = [IsGlobalAdminOrReadOnly]
    serializer_class = ManufacturerSerializer


class CollectionGroupViewSet(viewsets.ModelViewSet):
    """Collection groups: administered by global administrators, readable (as a summary) by everyone.

    Deleting a group that still has devices is refused.
    """

    queryset = CollectionGroup.objects.all()
    permission_classes = [IsGlobalAdminOrReadOnly]

    def get_serializer_class(self):
        return CollectionGroupSerializer if access.is_global_admin(self.request.user) else SummarySerializer

    def perform_update(self, serializer):
        old_queue = serializer.instance.rabbitmq_queue_id
        group = serializer.save()
        if group.rabbitmq_queue_id != old_queue:
            worker_registry.bump_collection_group(group)

    def destroy(self, request, *args, **kwargs):
        instance = self.get_object()
        if instance.device_count > 0:
            return response.Response(
                {'error': f'"{instance.name}" still has {instance.device_count} device(s).'},
                status=status.HTTP_409_CONFLICT,
            )
        instance.delete()
        return response.Response(status=status.HTTP_204_NO_CONTENT)


class BackupMethodViewSet(viewsets.ViewSet):
    """Backup methods (collector drivers) offered by approved collectors."""

    permission_classes = [IsAuthenticated]

    def list(self, request):
        data = [
            {
                'key': d['key'],
                'friendly_name': d['name'],
                'description': d['description'],
                'is_binary': d['is_binary'],
                'params_schema': d['params_schema'],
                'version': d['version'],
                'versions': d['versions'],
                'collectors': d['workers'],
            }
            for d in driver_catalogue().values()
        ]
        return response.Response(data, status=status.HTTP_200_OK)


class DeactivateSerializer(serializers.Serializer):
    reason = serializers.CharField(max_length=200, required=False, allow_blank=True, default='')


class PurgeSerializer(serializers.Serializer):
    confirm = serializers.CharField(help_text='The device name, typed to confirm')


class DeviceViewSet(viewsets.ModelViewSet):
    """Devices in the device groups the user can view (a device in another group is a 404).

    Creating, changing and deleting a device needs ``admin`` on its group (on both
    groups when moving it); ungrouped devices are for global administrators.
    ``POST {id}/backup_now/`` needs ``backup_now``. Retiring a device
    (``deactivate/``, ``reactivate/``, and ``DELETE`` once it is deletable) needs
    ``admin``; ``purge/`` is for global administrators (devices.lifecycle).
    ``?lifecycle=active|inactive|deletable`` filters the list.
    """

    serializer_class = DeviceSerializer
    permission_classes = [HasDeviceGroupPermission('view')]

    def get_queryset(self):
        devices = Device.objects.select_related(
            'device_type',
            'manufacturer',
            'collection_group',
            'device_group',
            'retention_policy',
            'inactive_by',
            'purge_requested_by',
        )
        devices = lifecycle.with_lifecycle(access.devices_for(self.request.user, 'view', devices))
        state = self.request.query_params.get('lifecycle')
        if self.action == 'list' and state:
            if state not in (lifecycle.ACTIVE, lifecycle.INACTIVE, lifecycle.DELETABLE):
                raise ValidationError({'lifecycle': 'Use active, inactive or deletable.'})
            devices = lifecycle.filter_lifecycle(devices, state)
        return devices

    def get_serializer_class(self):
        if self.action in ['create', 'update', 'partial_update']:
            return DeviceWriteSerializer
        if self.action == 'retrieve':
            return DeviceDetailedSerializer
        return DeviceSerializer

    def _require_admin(self, device_group):
        if not access.can(self.request.user, 'admin', device_group):
            if device_group is None:
                raise PermissionDenied('Only global administrators manage devices that are in no device group.')
            raise PermissionDenied('You need the "admin" permission on this device group.')

    def perform_create(self, serializer):
        self._require_admin(serializer.validated_data.get('device_group'))
        serializer.save()

    def perform_update(self, serializer):
        self._require_admin(serializer.instance.device_group)
        if 'device_group' in serializer.validated_data:
            self._require_admin(serializer.validated_data['device_group'])
        serializer.save()

    def destroy(self, request, *args, **kwargs):
        device = self.get_object()
        self._require_admin(device.device_group)
        group = device.device_group_id
        try:
            snapshot = lifecycle.delete(device)
        except lifecycle.LifecycleError as exc:
            return response.Response({'error': str(exc)}, status=status.HTTP_409_CONFLICT)
        record(request, 'device.delete', resource=str(snapshot['device']), device_group=group, details=snapshot)
        return response.Response(status=status.HTTP_204_NO_CONTENT)

    def _detail(self) -> response.Response:
        return response.Response(
            DeviceDetailedSerializer(self.get_object(), context=self.get_serializer_context()).data
        )

    @decorators.action(detail=True, methods=['post'], permission_classes=[HasDeviceGroupPermission('backup_now')])
    def backup_now(self, request, pk=None):
        return device_backup_now(request, self.get_object())

    @decorators.action(detail=True, methods=['post'], permission_classes=[HasDeviceGroupPermission('admin')])
    def deactivate(self, request, pk=None):
        """Mark the device inactive: no more backups, and its retention policy's hold begins."""
        body = DeactivateSerializer(data=request.data)
        body.is_valid(raise_exception=True)
        try:
            device = lifecycle.deactivate(self.get_object(), request.user, body.validated_data['reason'])
        except lifecycle.LifecycleError as exc:
            return response.Response({'error': str(exc)}, status=status.HTTP_400_BAD_REQUEST)
        record(
            request,
            'device.deactivate',
            resource=str(device.pk),
            device_group=device.device_group_id,
            details={'device': device.pk, 'device_name': device.name, 'reason': device.inactive_reason},
        )
        return self._detail()

    @decorators.action(detail=True, methods=['post'], permission_classes=[HasDeviceGroupPermission('admin')])
    def reactivate(self, request, pk=None):
        """Put an inactive device back in service."""
        try:
            device = lifecycle.reactivate(self.get_object())
        except lifecycle.LifecycleError as exc:
            return response.Response({'error': str(exc)}, status=status.HTTP_400_BAD_REQUEST)
        record(
            request,
            'device.reactivate',
            resource=str(device.pk),
            device_group=device.device_group_id,
            details={'device': device.pk, 'device_name': device.name},
        )
        return self._detail()

    @decorators.action(detail=True, methods=['post'], permission_classes=[IsGlobalAdmin])
    def purge(self, request, pk=None):
        """End an inactive device's hold now: unpin and delete all of its backups."""
        device = self.get_object()
        body = PurgeSerializer(data=request.data)
        body.is_valid(raise_exception=True)
        if body.validated_data['confirm'] != device.name:
            return response.Response(
                {'error': 'Type the device name to confirm the purge.'}, status=status.HTTP_400_BAD_REQUEST
            )
        try:
            result = lifecycle.purge(device, request.user)
        except lifecycle.LifecycleError as exc:
            return response.Response({'error': str(exc)}, status=status.HTTP_400_BAD_REQUEST)
        record(
            request,
            'device.purge',
            resource=str(device.pk),
            device_group=device.device_group_id,
            details={
                'device': device.pk,
                'device_name': device.name,
                'requested': len(result.requested),
                'requested_bytes': sum(job.size_bytes or 0 for job in result.requested),
                'unpinned': result.unpinned,
            },
        )
        return self._detail()


@decorators.api_view(['GET'])
@decorators.permission_classes([IsAuthenticated])
def timezone_config(request):
    """Return the configured application timezone"""
    from core.timezone_utils import get_timezone_name

    return response.Response({'timezone': get_timezone_name()})


class WorkerViewSet(
    mixins.ListModelMixin,
    mixins.RetrieveModelMixin,
    mixins.UpdateModelMixin,
    mixins.DestroyModelMixin,
    viewsets.GenericViewSet,
):
    """Registered workers: approve, assign, revoke and forget.

    - PATCH: change name/role/assignment of an approved worker (pushes a new assignment)
    - POST {id}/approve/: approve a pending (or revoked) worker with a role and assignment
    - POST {id}/revoke/: stop the worker consuming anything
    - DELETE: forget the worker (revoking it first); a live worker registers again as pending
    - GET orchestrator/: this orchestrator's key fingerprint, to compare with what workers pinned
    - GET/PATCH {id}/receiver/: a push receiver's settings (protocols, ports, login, size limit)
    - GET {id}/rejections/: the latest pushes a receiver refused
    """

    queryset = Worker.objects.prefetch_related('collection_groups').select_related('approved_by')
    serializer_class = WorkerSerializer
    permission_classes = [IsGlobalAdmin]
    http_method_names = ['get', 'post', 'patch', 'delete']

    def perform_update(self, serializer):
        changes = dict(serializer.validated_data)
        # A worker has one role: switching it drops the other role's assignment.
        role = changes.get('role', serializer.instance.role)
        if role != ROLE_COLLECTOR:
            changes['collection_groups'] = []
        if role != ROLE_STORAGE:
            changes['storage_targets'] = []
        worker_registry.update_assignment(serializer.instance, **changes)

    def perform_destroy(self, instance):
        if instance.status == STATUS_APPROVED:
            worker_registry.revoke(instance)
        instance.delete()

    @decorators.action(detail=True, methods=['post'])
    def approve(self, request, pk=None):
        worker = self.get_object()
        approval = WorkerApprovalSerializer(data=request.data)
        approval.is_valid(raise_exception=True)
        data = approval.validated_data
        # Reuse the worker serializer's capability checks.
        check = WorkerSerializer(
            worker,
            data={'role': data['role']},
            partial=True,
        )
        check.is_valid(raise_exception=True)
        targets = data.get('storage_targets', []) if data['role'] == ROLE_STORAGE else []
        problems = worker_registry.approval_target_problems(worker, targets)
        if problems:
            return response.Response({'storage_targets': problems}, status=status.HTTP_400_BAD_REQUEST)
        worker_registry.approve(
            worker,
            role=data['role'],
            user=request.user,
            collection_groups=data.get('collection_groups', []),
            storage_targets=targets,
        )
        return response.Response(WorkerSerializer(worker, context=self.get_serializer_context()).data)

    @decorators.action(detail=True, methods=['post'])
    def revoke(self, request, pk=None):
        worker = worker_registry.revoke(self.get_object())
        return response.Response(WorkerSerializer(worker, context=self.get_serializer_context()).data)

    def _receiver(self):
        worker = self.get_object()
        if worker.role != ROLE_RECEIVER:
            raise NotFound('This worker is not a push receiver.')
        return worker

    @decorators.action(detail=True, methods=['get', 'patch'])
    def receiver(self, request, pk=None):
        """What a receiver listens for. Saving sends it a new assignment."""
        from push.api import ReceiverSettingsSerializer
        from push.service import settings_for

        worker = self._receiver()
        settings = settings_for(worker)
        if request.method == 'GET':
            return response.Response(ReceiverSettingsSerializer(settings).data)
        serializer = ReceiverSettingsSerializer(settings, data=request.data, partial=True)
        serializer.is_valid(raise_exception=True)
        password_changed = 'ssh_password' in serializer.validated_data
        serializer.save()
        details = {k: v for k, v in serializer.data.items() if k != 'updated_at'}
        record(
            request, 'receiver.update', resource=worker.name, details={**details, 'password_changed': password_changed}
        )
        if worker.status == STATUS_APPROVED:
            worker_registry.update_assignment(worker)
        return response.Response(serializer.data)

    @decorators.action(detail=True, methods=['get'])
    def rejections(self, request, pk=None):
        """The latest pushes this receiver refused (or the orchestrator discarded), newest first."""
        from push.api import PushRejectionSerializer

        worker = self._receiver()
        return response.Response(PushRejectionSerializer(worker.push_rejections.all()[:100], many=True).data)

    @decorators.action(detail=False, methods=['get'])
    def orchestrator(self, request):
        from core.signing import fingerprint

        return response.Response(
            {
                'fingerprint': fingerprint(),
                'online_timeout_seconds': settings.DEVICEVAULT_WORKER_ONLINE_TIMEOUT_SEC,
            }
        )


def _changes(serializer) -> dict:
    """The fields a write set, as the API renders them."""
    return {field: serializer.data[field] for field in serializer.validated_data}


class RetentionPolicyViewSet(viewsets.ModelViewSet):
    """Retention policies. Changes are audited, since they decide what is deleted.

    ``{id}/preview/`` (global administrators): what the policy expires now, by device.
    """

    queryset = RetentionPolicy.objects.all()
    permission_classes = [IsGlobalAdminOrReadOnly]
    serializer_class = RetentionPolicySerializer

    def _audit(self, action: str, policy: RetentionPolicy, data: dict):
        record(self.request, action, resource=str(policy.pk), details={'policy': policy.name, **data})

    def perform_create(self, serializer):
        policy = serializer.save()
        self._audit('retention_policy.create', policy, _changes(serializer))

    def perform_update(self, serializer):
        policy = serializer.save()
        self._audit('retention_policy.update', policy, _changes(serializer))

    def perform_destroy(self, instance):
        self._audit('retention_policy.delete', instance, {})
        instance.delete()

    @decorators.action(detail=True, methods=['get'], permission_classes=[IsGlobalAdmin])
    def preview(self, request, pk=None):
        from backups import retention

        found = retention.plan(self.get_object())
        return response.Response(
            {
                'expired': len(found.jobs),
                'expired_bytes': found.bytes,
                'kept_undeletable': found.kept,
                'devices': [
                    {
                        'device': device.pk,
                        'device_name': device.name,
                        'backups': len(jobs),
                        'bytes': sum(job.size_bytes or 0 for job in jobs),
                        'oldest': jobs[-1].created_at,
                        'newest': jobs[0].created_at,
                    }
                    for device, jobs in found.expired.items()
                ],
            }
        )


class BackupScheduleViewSet(viewsets.ModelViewSet):
    queryset = BackupSchedule.objects.all()
    permission_classes = [IsGlobalAdminOrReadOnly]
    serializer_class = BackupScheduleSerializer


class CredentialViewSet(viewsets.ModelViewSet):
    """Credentials: global ones (no owner) and those owned by a device group.

    Lists global credentials and those of groups the user administers. Global
    credentials are written by global administrators, owned ones by the
    administrators of their group. Secret data is write-only.
    """

    serializer_class = CredentialSerializer
    permission_classes = [IsAuthenticated]

    def get_queryset(self):
        return access.credentials_for(self.request.user, Credential.objects.select_related('device_group'))

    def _require_owner_admin(self, device_group):
        if not access.can(self.request.user, 'admin', device_group):
            if device_group is None:
                raise PermissionDenied('Only global administrators manage global credentials.')
            raise PermissionDenied('You need the "admin" permission on the owning device group.')

    def perform_create(self, serializer):
        self._require_owner_admin(serializer.validated_data.get('device_group'))
        serializer.save()

    def perform_update(self, serializer):
        self._require_owner_admin(serializer.instance.device_group)
        if 'device_group' in serializer.validated_data:
            new_owner = serializer.validated_data['device_group']
            self._require_owner_admin(new_owner)
            # Devices may use only global credentials or their own group's.
            if new_owner is not None and serializer.instance.device_set.exclude(device_group=new_owner).exists():
                raise serializers.ValidationError({'device_group': 'Devices outside that group use this credential.'})
        serializer.save()

    def perform_destroy(self, instance):
        self._require_owner_admin(instance.device_group)
        instance.delete()


class CredentialTypeViewSet(viewsets.ModelViewSet):
    queryset = CredentialType.objects.all()
    permission_classes = [IsGlobalAdminOrReadOnly]
    serializer_class = CredentialTypeSerializer


@decorators.api_view(['GET'])
@decorators.authentication_classes([])
@decorators.permission_classes([AllowAny])
def health(request):
    """Liveness/readiness probe: the process is serving and the database is reachable."""
    from django.db import connection

    try:
        connection.ensure_connection()
    except Exception:
        return response.Response({'status': 'unavailable'}, status=status.HTTP_503_SERVICE_UNAVAILABLE)
    return response.Response({'status': 'ok'})


@decorators.api_view(['GET'])
@decorators.authentication_classes([])
@decorators.permission_classes([AllowAny])
def version_info(request):
    """The running release; public, since the sign-in page shows it."""
    from devicevault_protocol.version import version

    return response.Response({'version': version()})


@decorators.api_view(['GET'])
@decorators.permission_classes([IsAuthenticated])
def onboarding(request):
    # Configuration is supplied by the deployment environment, so an
    # orchestrator that is serving requests is configured by definition.
    return response.Response({'configured': True})


class UserPreferencesView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request):
        profile, _ = UserProfile.objects.get_or_create(user=request.user)
        return response.Response(UserProfileSerializer(profile).data, status=status.HTTP_200_OK)

    def patch(self, request):
        profile, _ = UserProfile.objects.get_or_create(user=request.user)
        serializer = UserProfileSerializer(profile, data=request.data, partial=True)
        serializer.is_valid(raise_exception=True)
        serializer.save()
        return response.Response(serializer.data, status=status.HTTP_200_OK)


class DeviceGroupViewSet(viewsets.ModelViewSet):
    """Device groups the user can view; creating, renaming and deleting them is for global administrators.

    A group that still has devices or owns credentials cannot be deleted.
    """

    serializer_class = DeviceGroupSerializer
    permission_classes = [IsGlobalAdminOrReadOnly]

    def get_queryset(self):
        return access.visible_device_groups(self.request.user)

    def destroy(self, request, *args, **kwargs):
        try:
            return super().destroy(request, *args, **kwargs)
        except ProtectedError as exc:
            return protected_conflict(exc, 'device group')
