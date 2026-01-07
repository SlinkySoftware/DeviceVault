from rest_framework import viewsets, decorators, response, status
from rest_framework.views import APIView
from rest_framework.authtoken.models import Token
from rest_framework.permissions import AllowAny, IsAuthenticated
from django.contrib.auth.models import User
from django.contrib.auth import authenticate
from django.db.models import Count, Avg
from django.utils import timezone
from datetime import timedelta
from devices.models import DeviceType, Manufacturer, Device
from backups.models import Backup
from policies.models import RetentionPolicy, BackupSchedule
from locations.models import BackupLocation
from credentials.models import Credential, CredentialType
from core.models import DashboardLayout
from devices.models import (
    DeviceGroup, DeviceGroupRole, DeviceGroupPermission,
    UserDeviceGroupRole, GroupDeviceGroupRole
)
from django.contrib.auth.models import Group
from audit.models import AuditLog
from devices.permissions import user_has_device_group_permission, user_get_device_group_permissions
from .serializers import (
    DeviceTypeSerializer, ManufacturerSerializer, DeviceSerializer,
    BackupSerializer, RetentionPolicySerializer, BackupLocationSerializer,
    CredentialSerializer, CredentialTypeSerializer,
    UserSerializer, AuditLogSerializer,
    LoginSerializer, UserUpdateSerializer, ChangePasswordSerializer, DashboardLayoutSerializer,
    UserProfileSerializer, BackupScheduleSerializer, GroupSerializer,
    DeviceGroupSerializer, DeviceGroupRoleSerializer, DeviceGroupPermissionSerializer,
    UserDeviceGroupRoleSerializer, GroupDeviceGroupRoleSerializer, DeviceDetailedSerializer
)
import difflib, os

class DeviceTypeViewSet(viewsets.ModelViewSet):
    queryset = DeviceType.objects.all()
    serializer_class = DeviceTypeSerializer
class ManufacturerViewSet(viewsets.ModelViewSet):
    queryset = Manufacturer.objects.all()
    serializer_class = ManufacturerSerializer


class BackupMethodViewSet(viewsets.ReadOnlyModelViewSet):
    """
    Read-only ViewSet for listing available backup method plugins
    
    Returns all plugins discovered under backups.plugins with their
    friendly_name and description.
    """
    permission_classes = [IsAuthenticated]
    
    def list(self, request):
        from backups.plugins import list_plugins
        plugins = list_plugins()
        data = [
            {
                'key': p.key,
                'friendly_name': p.friendly_name,
                'description': p.description
            }
            for p in plugins
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
        """Use detailed serializer for retrieve and update"""
        if self.action in ['retrieve', 'update', 'partial_update']:
            return DeviceDetailedSerializer
        return DeviceSerializer
    
    def get_queryset(self):
        """Filter devices based on user's device group access"""
        from devices.permissions import user_get_accessible_device_groups
        
        user = self.request.user
        
        if user.is_staff or user.is_superuser:
            return Device.objects.all()
        
        # Only return devices from groups the user has access to
        accessible_groups = user_get_accessible_device_groups(user)
        return Device.objects.filter(device_group__in=accessible_groups)
    
    def perform_destroy(self, instance):
        """Check delete permission before deleting"""
        from devices.permissions import user_has_device_group_permission
        
        if not self.request.user.is_staff and not self.request.user.is_superuser:
            if not instance.device_group:
                raise serializers.ValidationError("Device has no device group")
            
            if not user_has_device_group_permission(self.request.user, instance.device_group, 'delete_device'):
                raise serializers.ValidationError("You do not have permission to delete devices in this group")
class BackupViewSet(viewsets.ModelViewSet):
    queryset = Backup.objects.all()
    serializer_class = BackupSerializer
class RetentionPolicyViewSet(viewsets.ModelViewSet):
    queryset = RetentionPolicy.objects.all()
    serializer_class = RetentionPolicySerializer
class BackupScheduleViewSet(viewsets.ModelViewSet):
    queryset = BackupSchedule.objects.all()
    serializer_class = BackupScheduleSerializer
class BackupLocationViewSet(viewsets.ModelViewSet):
    queryset = BackupLocation.objects.all()
    serializer_class = BackupLocationSerializer
class CredentialViewSet(viewsets.ModelViewSet):
    queryset = Credential.objects.all()
    serializer_class = CredentialSerializer
class CredentialTypeViewSet(viewsets.ModelViewSet):
    queryset = CredentialType.objects.all()
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
    serializer_class = GroupSerializer

    def destroy(self, request, *args, **kwargs):
        return super().destroy(request, *args, **kwargs)
class UserViewSet(viewsets.ModelViewSet):
    queryset = User.objects.all()
    serializer_class = UserSerializer
    permission_classes = [IsAuthenticated]

    def _is_jit_provisioned(self, user):
        try:
            has_social = hasattr(user, 'social_auth') and user.social_auth.exists()
        except Exception:
            has_social = False
        return (not user.has_usable_password()) or has_social
    
    def _is_local_auth_enabled(self):
        """Check if local auth is enabled in config.yaml"""
        from pathlib import Path
        import yaml
        
        config_path = os.environ.get('DEVICEVAULT_CONFIG', str(Path(__file__).resolve().parent.parent / 'config' / 'config.yaml'))
        if not os.path.exists(config_path):
            return False
        
        try:
            with open(config_path) as f:
                config = yaml.safe_load(f)
            auth_config = config.get('auth', {})
            return auth_config.get('local_enabled', False) or auth_config.get('type', '').lower() == 'local'
        except Exception:
            return False
    
    def create(self, request, *args, **kwargs):
        """Create a new user - only allowed if local auth is enabled"""
        # Only staff can create users
        if not request.user.is_staff:
            return response.Response({'detail': 'Not authorized'}, status=status.HTTP_403_FORBIDDEN)
        
        # Check if local auth is enabled
        if not self._is_local_auth_enabled():
            return response.Response(
                {'detail': 'User creation is only allowed when local authentication is enabled. Configure local auth in settings first.'},
                status=status.HTTP_403_FORBIDDEN
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
                status=status.HTTP_403_FORBIDDEN
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
                {'detail': 'Cannot delete the last superuser account.'},
                status=status.HTTP_403_FORBIDDEN
            )
        
        return super().destroy(request, *args, **kwargs)

    @decorators.action(detail=True, methods=['patch'], permission_classes=[IsAuthenticated])
    def update_details(self, request, pk=None):
        # Only staff can edit other users
        if not request.user.is_staff:
            return response.Response({'detail': 'Not authorized'}, status=status.HTTP_403_FORBIDDEN)
        user = self.get_object()
        if self._is_jit_provisioned(user):
            return response.Response({'detail': 'Profile is managed by external identity provider and cannot be edited.'}, status=status.HTTP_403_FORBIDDEN)
        serializer = UserUpdateSerializer(instance=user, data=request.data, partial=True)
        if serializer.is_valid():
            serializer.save()
            return response.Response(UserSerializer(user).data, status=status.HTTP_200_OK)
        return response.Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)

class AuditLogViewSet(viewsets.ReadOnlyModelViewSet):
    queryset = AuditLog.objects.all().order_by('-created_at')
    serializer_class = AuditLogSerializer

@decorators.api_view(['GET'])
def onboarding(request):
    from pathlib import Path
    config_path = os.environ.get('DEVICEVAULT_CONFIG', str(Path(__file__).resolve().parent.parent / 'config' / 'config.yaml'))
    exists = os.path.exists(config_path)
    return response.Response({'configured': exists})

@decorators.api_view(['GET'])
def dashboard_stats(request):
    now = timezone.now()
    yesterday = now - timedelta(days=1)
    week_ago = now - timedelta(days=7)
    
    device_count = Device.objects.values('device_type__name').annotate(count=Count('id'))
    success_24h = Backup.objects.filter(timestamp__gte=yesterday, status='success').count()
    failed_24h = Backup.objects.filter(timestamp__gte=yesterday, status='failed').count()
    avg_duration = 0  # Would need duration field in Backup model
    
    # Get daily backup stats for chart
    daily_stats = []
    for i in range(7):
        day = now - timedelta(days=6-i)
        day_start = day.replace(hour=0, minute=0, second=0, microsecond=0)
        day_end = day_start + timedelta(days=1)
        success = Backup.objects.filter(timestamp__gte=day_start, timestamp__lt=day_end, status='success').count()
        failed = Backup.objects.filter(timestamp__gte=day_start, timestamp__lt=day_end, status='failed').count()
        total = success + failed
        daily_stats.append({
            'date': day_start.strftime('%Y-%m-%d'),
            'success': success,
            'failed': failed,
            'rate': (success / total * 100) if total > 0 else 0
        })
    
    return response.Response({
        'devicesByType': dict((item['device_type__name'], item['count']) for item in device_count),
        'success24h': success_24h,
        'failed24h': failed_24h,
        'avgDuration': avg_duration,
        'dailyStats': daily_stats
    })

class AuthConfigView(APIView):
    def get(self, request):
        from pathlib import Path
        import yaml
        
        config_path = os.environ.get('DEVICEVAULT_CONFIG', str(Path(__file__).resolve().parent.parent / 'config' / 'config.yaml'))
        local_enabled = False
        auth_type = None
        
        if os.path.exists(config_path):
            try:
                with open(config_path) as f:
                    config = yaml.safe_load(f)
                auth_config = config.get('auth', {})
                local_enabled = auth_config.get('local_enabled', False)
                auth_type = auth_config.get('type')
            except Exception:
                pass
        
        return response.Response({
            'providers': ['LDAP','SAML','EntraID','Local'],
            'local_enabled': local_enabled,
            'auth_type': auth_type
        })

class LoginView(APIView):
    permission_classes = [AllowAny]
    
    def post(self, request):
        serializer = LoginSerializer(data=request.data)
        if serializer.is_valid():
            user = serializer.validated_data['user']
            token, created = Token.objects.get_or_create(user=user)
            user_serializer = UserSerializer(user)
            return response.Response({
                'token': token.key,
                'user': user_serializer.data
            }, status=status.HTTP_200_OK)
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
        return response.Response({
            **serializer.data,
            'editable': editable,
            'is_admin': is_admin,
            'ignore_tags': ignore_tags
        }, status=status.HTTP_200_OK)

    def patch(self, request):
        if self._is_jit_provisioned(request.user):
            return response.Response({'detail': 'Profile is managed by external identity provider and cannot be edited.'}, status=status.HTTP_403_FORBIDDEN)
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
        layout, created = DashboardLayout.objects.get_or_create(
            user=request.user,
            is_default=False
        )
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
        layout, created = DashboardLayout.objects.get_or_create(
            is_default=True,
            user__isnull=True
        )
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


@decorators.api_view(['POST'])
def compare_backups(request):
    a = request.data.get('a_path'); b = request.data.get('b_path')
    if not (a and b and os.path.exists(a) and os.path.exists(b)):
        return response.Response({'error':'invalid paths'}, status=status.HTTP_400_BAD_REQUEST)
    with open(a) as fa, open(b) as fb:
        a_text = fa.read().splitlines(); b_text = fb.read().splitlines()
    diff = difflib.unified_diff(a_text, b_text, fromfile=a, tofile=b, lineterm='')
    return response.Response({'diff':''.join(list(diff))})

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
    permission_classes = [IsAuthenticated]
    
    def get_queryset(self):
        """Only return device groups the user has access to"""
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
    permission_classes = [IsAuthenticated]
    
    def get_queryset(self):
        """Only return roles for device groups the user has access to"""
        from devices.permissions import user_get_accessible_device_groups
        
        if self.request.user.is_staff or self.request.user.is_superuser:
            return DeviceGroupRole.objects.all()
        
        accessible_groups = user_get_accessible_device_groups(self.request.user)
        return DeviceGroupRole.objects.filter(device_group__in=accessible_groups)


class DeviceGroupPermissionViewSet(viewsets.ReadOnlyModelViewSet):
    """
    ViewSet for viewing device group permissions (read-only)
    
    Permission Codes:
    - view_configuration: Can view device configuration backups
    - view_backups: Can view/download backup history
    - edit_configuration: Can modify device configuration
    - add_device: Can add devices to the group
    - delete_device: Can delete devices from the group
    - enable_device: Can enable/disable devices in the group
    """
    queryset = DeviceGroupPermission.objects.all()
    serializer_class = DeviceGroupPermissionSerializer
    permission_classes = [IsAuthenticated]


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
    permission_classes = [IsAuthenticated]


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
    permission_classes = [IsAuthenticated]