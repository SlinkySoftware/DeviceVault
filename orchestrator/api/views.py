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
from django.contrib.auth.models import Group, Permission, User
from rest_framework import decorators, mixins, response, status, viewsets
from rest_framework.authtoken.models import Token
from rest_framework.exceptions import PermissionDenied
from rest_framework.permissions import AllowAny, IsAuthenticated
from rest_framework.views import APIView

from api.permissions import IsAdmin, IsAdminOrReadOnly
from audit.models import AuditLog
from backups.api import device_backup_now
from core import workers as worker_registry
from core.models import DashboardLayout, Worker
from core.workers import driver_catalogue
from credentials.models import Credential, CredentialType
from devices.models import (
    CollectionGroup,
    Device,
    DeviceGroup,
    DeviceGroupRole,
    DeviceType,
    GroupDeviceGroupRole,
    Manufacturer,
    UserDeviceGroupRole,
)
from devices.permissions import user_has_device_group_permission
from devicevault_protocol.registration import ROLE_COLLECTOR, ROLE_STORAGE, STATUS_APPROVED
from policies.models import BackupSchedule, RetentionPolicy

from .serializers import (
    AuditLogSerializer,
    BackupScheduleSerializer,
    ChangePasswordSerializer,
    CollectionGroupSerializer,
    CredentialSerializer,
    CredentialTypeSerializer,
    DashboardLayoutSerializer,
    DeviceDetailedSerializer,
    DeviceGroupRoleSerializer,
    DeviceGroupSerializer,
    DeviceSerializer,
    DeviceTypeSerializer,
    DeviceWriteSerializer,
    GroupDeviceGroupRoleSerializer,
    GroupSerializer,
    LoginSerializer,
    ManufacturerSerializer,
    RetentionPolicySerializer,
    UserDeviceGroupRoleSerializer,
    UserProfileSerializer,
    UserSerializer,
    UserUpdateSerializer,
    WorkerApprovalSerializer,
    WorkerSerializer,
)


class DeviceTypeViewSet(viewsets.ModelViewSet):
    queryset = DeviceType.objects.all()
    permission_classes = [IsAdminOrReadOnly]
    serializer_class = DeviceTypeSerializer


class ManufacturerViewSet(viewsets.ModelViewSet):
    queryset = Manufacturer.objects.all()
    permission_classes = [IsAdminOrReadOnly]
    serializer_class = ManufacturerSerializer


class CollectionGroupViewSet(viewsets.ModelViewSet):
    """
    ViewSet for managing collection groups

    Features:
    - Restricted to superuser only for all operations
    - Prevents deletion of collection groups that have devices assigned
    - Returns device count for each collection group

    Permissions:
    - Only superuser/staff users can access this endpoint
    """

    queryset = CollectionGroup.objects.all()
    serializer_class = CollectionGroupSerializer
    permission_classes = [IsAdminOrReadOnly]

    def perform_update(self, serializer):
        old_queue = serializer.instance.rabbitmq_queue_id
        group = serializer.save()
        if group.rabbitmq_queue_id != old_queue:
            worker_registry.bump_collection_group(group)

    def perform_destroy(self, instance):
        """Prevent deletion if any devices are assigned to this collection group"""
        if instance.device_count > 0:
            from django.core.exceptions import ValidationError

            raise ValidationError(
                f'Cannot delete collection group "{instance.name}": {instance.device_count} device(s) are assigned to this group.'
            )
        instance.delete()


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


class DeviceViewSet(viewsets.ModelViewSet):
    """
    ViewSet for managing devices with RBAC support

    Features:
    - Filters devices based on user's device group access
    - Respects device group permissions for view/edit operations
    - Returns user's permissions in device detail
    """

    queryset = Device.objects.all()
    serializer_class = DeviceSerializer
    permission_classes = [IsAuthenticated]

    def get_serializer_class(self):
        if self.action in ['create', 'update', 'partial_update']:
            return DeviceWriteSerializer
        if self.action == 'retrieve':
            return DeviceDetailedSerializer
        return DeviceSerializer

    def _require_modify(self, device_group):
        from devices.permissions import user_has_device_group_django_permission

        user = self.request.user
        if user.is_staff or user.is_superuser:
            return
        if device_group is None or not user_has_device_group_django_permission(user, device_group, 'modify'):
            raise PermissionDenied('You do not have permission to modify devices in this device group')

    def perform_create(self, serializer):
        self._require_modify(serializer.validated_data.get('device_group'))
        serializer.save()

    def perform_update(self, serializer):
        self._require_modify(serializer.instance.device_group)
        if 'device_group' in serializer.validated_data:
            self._require_modify(serializer.validated_data['device_group'])
        serializer.save()

    def get_queryset(self):
        """Devices in groups the user can access."""
        from devices.permissions import user_get_accessible_device_groups

        user = self.request.user
        devices = Device.objects.select_related('device_type', 'manufacturer', 'collection_group', 'device_group')
        if user.is_staff or user.is_superuser:
            return devices
        return devices.filter(device_group__in=user_get_accessible_device_groups(user))

    def perform_destroy(self, instance):
        """Check delete permission before deleting"""
        if not self.request.user.is_staff and not self.request.user.is_superuser:
            if not instance.device_group:
                raise PermissionDenied('Device has no device group')

            if not user_has_device_group_permission(self.request.user, instance.device_group, 'delete_device'):
                raise PermissionDenied('You do not have permission to delete devices in this group')

        instance.delete()

    @decorators.action(detail=True, methods=['post'])
    def backup_now(self, request, pk=None):
        return device_backup_now(request, self.get_object())


@decorators.api_view(['GET'])
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
    """

    queryset = Worker.objects.prefetch_related('collection_groups').select_related('approved_by')
    serializer_class = WorkerSerializer
    permission_classes = [IsAdmin]
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

    @decorators.action(detail=False, methods=['get'])
    def orchestrator(self, request):
        from core.signing import fingerprint

        return response.Response(
            {
                'fingerprint': fingerprint(),
                'online_timeout_seconds': settings.DEVICEVAULT_WORKER_ONLINE_TIMEOUT_SEC,
            }
        )


class RetentionPolicyViewSet(viewsets.ModelViewSet):
    queryset = RetentionPolicy.objects.all()
    permission_classes = [IsAdminOrReadOnly]
    serializer_class = RetentionPolicySerializer


class BackupScheduleViewSet(viewsets.ModelViewSet):
    queryset = BackupSchedule.objects.all()
    permission_classes = [IsAdminOrReadOnly]
    serializer_class = BackupScheduleSerializer


class CredentialViewSet(viewsets.ModelViewSet):
    queryset = Credential.objects.all()
    permission_classes = [IsAdminOrReadOnly]
    serializer_class = CredentialSerializer


class CredentialTypeViewSet(viewsets.ModelViewSet):
    queryset = CredentialType.objects.all()
    permission_classes = [IsAdminOrReadOnly]
    serializer_class = CredentialTypeSerializer


class GroupViewSet(viewsets.ModelViewSet):
    """
    ViewSet for managing user groups with label assignments

    Endpoints:
    - GET /groups/ - List all groups
    - POST /groups/ - Create new group
    - GET /groups/{id}/ - Get group details
    - PATCH /groups/{id}/ - Update group
    - DELETE /groups/{id}/ - Delete group
    """

    queryset = Group.objects.all()
    permission_classes = [IsAdmin]
    serializer_class = GroupSerializer

    def destroy(self, request, *args, **kwargs):
        return super().destroy(request, *args, **kwargs)


class UserViewSet(viewsets.ModelViewSet):
    queryset = User.objects.all()
    serializer_class = UserSerializer
    permission_classes = [IsAdmin]

    def _is_jit_provisioned(self, user):
        try:
            has_social = hasattr(user, 'social_auth') and user.social_auth.exists()
        except Exception:
            has_social = False
        return (not user.has_usable_password()) or has_social

    def _is_local_auth_enabled(self):
        return settings.DEVICEVAULT_LOCAL_AUTH_ENABLED

    def create(self, request, *args, **kwargs):
        """Create a new user - only allowed if local auth is enabled"""
        # Only staff can create users
        if not request.user.is_staff:
            return response.Response({'detail': 'Not authorized'}, status=status.HTTP_403_FORBIDDEN)

        # Check if local auth is enabled
        if not self._is_local_auth_enabled():
            return response.Response(
                {
                    'detail': 'User creation is only allowed when local authentication is enabled. Configure local auth in settings first.'
                },
                status=status.HTTP_403_FORBIDDEN,
            )

        return super().create(request, *args, **kwargs)

    def update(self, request, *args, **kwargs):
        """Update a user - only staff can do this"""
        if not request.user.is_staff:
            return response.Response({'detail': 'Not authorized'}, status=status.HTTP_403_FORBIDDEN)

        user = self.get_object()
        if self._is_jit_provisioned(user):
            return response.Response(
                {'detail': 'Profile is managed by external identity provider and cannot be edited.'},
                status=status.HTTP_403_FORBIDDEN,
            )

        return super().update(request, *args, **kwargs)

    def destroy(self, request, *args, **kwargs):
        """Delete a user - only staff can do this"""
        if not request.user.is_staff:
            return response.Response({'detail': 'Not authorized'}, status=status.HTTP_403_FORBIDDEN)

        user = self.get_object()
        # Prevent deleting the last superuser
        if user.is_superuser and User.objects.filter(is_superuser=True).count() == 1:
            return response.Response(
                {'detail': 'Cannot delete the last superuser account.'}, status=status.HTTP_403_FORBIDDEN
            )

        return super().destroy(request, *args, **kwargs)

    @decorators.action(detail=True, methods=['patch'], permission_classes=[IsAuthenticated])
    def update_details(self, request, pk=None):
        # Only staff can edit other users
        if not request.user.is_staff:
            return response.Response({'detail': 'Not authorized'}, status=status.HTTP_403_FORBIDDEN)
        user = self.get_object()
        if self._is_jit_provisioned(user):
            return response.Response(
                {'detail': 'Profile is managed by external identity provider and cannot be edited.'},
                status=status.HTTP_403_FORBIDDEN,
            )
        serializer = UserUpdateSerializer(instance=user, data=request.data, partial=True)
        if serializer.is_valid():
            serializer.save()
            return response.Response(UserSerializer(user).data, status=status.HTTP_200_OK)
        return response.Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)


class AuditLogViewSet(viewsets.ReadOnlyModelViewSet):
    queryset = AuditLog.objects.all().order_by('-created_at')
    permission_classes = [IsAdmin]
    serializer_class = AuditLogSerializer


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
def onboarding(request):
    # Configuration is supplied by the deployment environment, so an
    # orchestrator that is serving requests is configured by definition.
    return response.Response({'configured': True})


class AuthConfigView(APIView):
    permission_classes = [AllowAny]

    def get(self, request):
        local_enabled = settings.DEVICEVAULT_LOCAL_AUTH_ENABLED
        auth_type = 'Local' if local_enabled else None

        return response.Response({'providers': ['Local'], 'local_enabled': local_enabled, 'auth_type': auth_type})


class LoginView(APIView):
    permission_classes = [AllowAny]

    def post(self, request):
        serializer = LoginSerializer(data=request.data)
        if serializer.is_valid():
            user = serializer.validated_data['user']
            token, created = Token.objects.get_or_create(user=user)
            user_serializer = UserSerializer(user)
            return response.Response({'token': token.key, 'user': user_serializer.data}, status=status.HTTP_200_OK)
        return response.Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)


class LogoutView(APIView):
    permission_classes = [IsAuthenticated]

    def post(self, request):
        request.user.auth_token.delete()
        return response.Response({'message': 'Logged out successfully'}, status=status.HTTP_200_OK)


class UserInfoView(APIView):
    permission_classes = [IsAuthenticated]

    def _is_jit_provisioned(self, user):
        # Heuristic: users from SSO/LDAP typically have unusable passwords
        # and may have social_auth relations. Local users have usable passwords.
        try:
            has_social = hasattr(user, 'social_auth') and user.social_auth.exists()
        except Exception:
            has_social = False
        return (not user.has_usable_password()) or has_social

    def get(self, request):
        serializer = UserSerializer(request.user)
        editable = not self._is_jit_provisioned(request.user)
        # Determine flags based on group membership
        # is_admin: staff users or members of 'Application Admin' group
        is_admin = request.user.is_staff or request.user.groups.filter(name__iexact='Application Admin').exists()
        # ignore_tags: no longer supported via custom group model; default to False
        ignore_tags = False
        return response.Response(
            {**serializer.data, 'editable': editable, 'is_admin': is_admin, 'ignore_tags': ignore_tags},
            status=status.HTTP_200_OK,
        )

    def patch(self, request):
        if self._is_jit_provisioned(request.user):
            return response.Response(
                {'detail': 'Profile is managed by external identity provider and cannot be edited.'},
                status=status.HTTP_403_FORBIDDEN,
            )
        serializer = UserUpdateSerializer(instance=request.user, data=request.data, partial=True)
        if serializer.is_valid():
            serializer.save()
            # Return updated details with editable flag
            data = UserSerializer(request.user).data
            data['editable'] = True
            return response.Response(data, status=status.HTTP_200_OK)
        return response.Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)


class ChangePasswordView(APIView):
    permission_classes = [IsAuthenticated]

    def post(self, request):
        serializer = ChangePasswordSerializer(data=request.data, context={'request': request})
        if serializer.is_valid():
            request.user.set_password(serializer.validated_data['new_password'])
            request.user.save()
            return response.Response({'message': 'Password changed successfully'}, status=status.HTTP_200_OK)
        return response.Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)


class DashboardLayoutView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request):
        # Try to get user's layout, fall back to default
        layout = DashboardLayout.objects.filter(user=request.user).first()
        if not layout:
            layout = DashboardLayout.objects.filter(is_default=True, user__isnull=True).first()
        if not layout:
            # Return empty default layout
            return response.Response({'layout': [], 'is_default': False}, status=status.HTTP_200_OK)
        serializer = DashboardLayoutSerializer(layout)
        return response.Response(serializer.data, status=status.HTTP_200_OK)

    def post(self, request):
        # Save or update user's layout
        layout, created = DashboardLayout.objects.get_or_create(user=request.user, is_default=False)
        layout.layout = request.data.get('layout', [])
        layout.save()
        serializer = DashboardLayoutSerializer(layout)
        return response.Response(serializer.data, status=status.HTTP_200_OK)


class DashboardDefaultLayoutView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request):
        # Get default layout (admin only)
        if not request.user.is_staff:
            return response.Response({'detail': 'Not authorized'}, status=status.HTTP_403_FORBIDDEN)
        layout = DashboardLayout.objects.filter(is_default=True, user__isnull=True).first()
        if not layout:
            return response.Response({'layout': [], 'is_default': True}, status=status.HTTP_200_OK)
        serializer = DashboardLayoutSerializer(layout)
        return response.Response(serializer.data, status=status.HTTP_200_OK)

    def post(self, request):
        # Save default layout (admin only)
        if not request.user.is_staff:
            return response.Response({'detail': 'Not authorized'}, status=status.HTTP_403_FORBIDDEN)
        layout, created = DashboardLayout.objects.get_or_create(is_default=True, user__isnull=True)
        layout.layout = request.data.get('layout', [])
        layout.save()
        serializer = DashboardLayoutSerializer(layout)
        return response.Response(serializer.data, status=status.HTTP_200_OK)


class UserPreferencesView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request):
        # Get user preferences (theme)
        from core.models import UserProfile

        profile, created = UserProfile.objects.get_or_create(user=request.user)
        serializer = UserProfileSerializer(profile)
        return response.Response(serializer.data, status=status.HTTP_200_OK)

    def patch(self, request):
        # Update user preferences
        from core.models import UserProfile

        profile, created = UserProfile.objects.get_or_create(user=request.user)
        serializer = UserProfileSerializer(profile, data=request.data, partial=True)
        if serializer.is_valid():
            serializer.save()
            return response.Response(serializer.data, status=status.HTTP_200_OK)
        return response.Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)


# ===== Device Group RBAC ViewSets =====


class DeviceGroupViewSet(viewsets.ModelViewSet):
    """
    ViewSet for managing device groups

    Endpoints:
    - GET /device-groups/ - List all device groups
    - POST /device-groups/ - Create new device group (admin only)
    - GET /device-groups/{id}/ - Get device group details
    - PATCH /device-groups/{id}/ - Update device group
    - DELETE /device-groups/{id}/ - Delete device group
    """

    queryset = DeviceGroup.objects.all()
    serializer_class = DeviceGroupSerializer
    permission_classes = [IsAdminOrReadOnly]

    def get_queryset(self):
        """Only return device groups the user can access via any Django device-group permission"""
        from devices.permissions import user_get_accessible_device_groups

        if self.request.user.is_staff or self.request.user.is_superuser:
            return DeviceGroup.objects.all()
        return user_get_accessible_device_groups(self.request.user)

    def perform_create(self, serializer):
        obj = serializer.save()
        # Ensure Django permissions exist for this device group
        from devices.models import DeviceGroupDjangoPermissions

        DeviceGroupDjangoPermissions.ensure_for_group(obj)

    def perform_update(self, serializer):
        instance = self.get_object()
        old_name = instance.name
        obj = serializer.save()
        if old_name != obj.name:
            from devices.models import DeviceGroupDjangoPermissions

            try:
                link = obj.django_permissions
            except DeviceGroupDjangoPermissions.DoesNotExist:
                link = DeviceGroupDjangoPermissions.ensure_for_group(obj)
            link.rename_to(obj.name)

    def perform_destroy(self, instance):
        # pre_delete signal enforces membership restriction
        # If deletion allowed, also clean up associated Django role groups
        # pre_delete signal will raise ValidationError if blocked. Proceed with deletion.
        return super().perform_destroy(instance)


class DeviceGroupRoleViewSet(viewsets.ModelViewSet):
    """
    ViewSet for managing device group roles

    Endpoints:
    - GET /device-group-roles/ - List all roles
    - POST /device-group-roles/ - Create new role (admin only)
    - GET /device-group-roles/{id}/ - Get role details
    - PATCH /device-group-roles/{id}/ - Update role
    - DELETE /device-group-roles/{id}/ - Delete role
    """

    queryset = DeviceGroupRole.objects.all()
    serializer_class = DeviceGroupRoleSerializer
    permission_classes = [IsAdmin]

    def get_queryset(self):
        """Only return roles for device groups the user has access to"""
        from devices.permissions import user_get_accessible_device_groups

        if self.request.user.is_staff or self.request.user.is_superuser:
            return DeviceGroupRole.objects.all()

        accessible_groups = user_get_accessible_device_groups(self.request.user)
        return DeviceGroupRole.objects.filter(device_group__in=accessible_groups)


class DeviceGroupPermissionViewSet(viewsets.ReadOnlyModelViewSet):
    """
    ViewSet for retrieving Django auth permissions for device groups

    Endpoints:
    - GET /device-group-permissions/ - List all device group Django permissions
    - GET /device-group-permissions/{id}/ - Get permission details

    These are the 4 auto-created Django auth permissions per device group:
    - Can View
    - Can Modify
    - Can View Backups
    - Can Backup Now

    Only superusers can access this endpoint.
    """

    queryset = Permission.objects.filter(codename__startswith='dg_').order_by('codename')
    permission_classes = [IsAdmin]

    def get_queryset(self):
        """Return Django auth permissions with dg_ prefix"""
        return Permission.objects.filter(codename__startswith='dg_').order_by('codename')

    def list(self, request, *args, **kwargs):
        """Return simplified permission list"""
        queryset = self.get_queryset()
        data = [{'id': p.id, 'codename': p.codename, 'name': p.name} for p in queryset]
        return response.Response(data)

    def retrieve(self, request, pk=None, *args, **kwargs):
        """Return single permission details"""
        try:
            permission = Permission.objects.get(pk=pk, codename__startswith='dg_')
            data = {'id': permission.id, 'codename': permission.codename, 'name': permission.name}
            return response.Response(data)
        except Permission.DoesNotExist:
            return response.Response({'error': 'Permission not found'}, status=status.HTTP_404_NOT_FOUND)


class UserDeviceGroupRoleViewSet(viewsets.ModelViewSet):
    """
    ViewSet for assigning device group roles to users

    Endpoints:
    - GET /user-device-group-roles/ - List assignments
    - POST /user-device-group-roles/ - Create new assignment (admin only)
    - DELETE /user-device-group-roles/{id}/ - Remove assignment
    """

    queryset = UserDeviceGroupRole.objects.all()
    serializer_class = UserDeviceGroupRoleSerializer
    permission_classes = [IsAdmin]

    def get_queryset(self):
        qs = super().get_queryset().select_related('role__device_group')
        user = self.request.query_params.get('user')
        return qs.filter(user_id=user) if user else qs


class GroupDeviceGroupRoleViewSet(viewsets.ModelViewSet):
    """
    ViewSet for assigning device group roles to auth groups

    Endpoints:
    - GET /group-device-group-roles/ - List assignments
    - POST /group-device-group-roles/ - Create new assignment (admin only)
    - DELETE /group-device-group-roles/{id}/ - Remove assignment
    """

    queryset = GroupDeviceGroupRole.objects.all()
    serializer_class = GroupDeviceGroupRoleSerializer
    permission_classes = [IsAdmin]

    def get_queryset(self):
        qs = super().get_queryset().select_related('role__device_group')
        auth_group = self.request.query_params.get('auth_group')
        return qs.filter(auth_group_id=auth_group) if auth_group else qs


class ThemeSettingsView(APIView):
    """
    API View for theme settings (superuser only for updates)

    GET: Public access to retrieve theme settings
    PUT: Superuser only to update theme settings
    """

    permission_classes = [AllowAny]

    def get(self, request):
        """Retrieve current theme settings"""
        from api.serializers import ThemeSettingsSerializer
        from core.theme_settings import ThemeSettings

        settings = ThemeSettings.load()
        serializer = ThemeSettingsSerializer(settings)
        return response.Response(serializer.data)

    def put(self, request):
        """Update theme settings (superuser only)"""
        from api.serializers import ThemeSettingsSerializer
        from core.theme_settings import ThemeSettings

        if not request.user.is_authenticated:
            return response.Response({'error': 'Authentication required'}, status=status.HTTP_401_UNAUTHORIZED)

        if not request.user.is_superuser:
            return response.Response(
                {'error': 'Only superusers can modify theme settings'}, status=status.HTTP_403_FORBIDDEN
            )

        settings = ThemeSettings.load()
        serializer = ThemeSettingsSerializer(settings, data=request.data, partial=True)

        if serializer.is_valid():
            serializer.save()
            return response.Response(serializer.data)

        return response.Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)
