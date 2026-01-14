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

from rest_framework import viewsets, decorators, response, status
from rest_framework.views import APIView
from rest_framework.authtoken.models import Token
from rest_framework.permissions import AllowAny, IsAuthenticated, IsAdminUser
from django.contrib.auth.models import User, Permission
from django.contrib.auth import authenticate
from django.db.models import Count, Avg, F, Q, Prefetch, OuterRef, Subquery
from django.utils import timezone
from datetime import timedelta
from core.timezone_utils import local_to_utc, utc_to_local
from devices.models import DeviceType, Manufacturer, Device, CollectionGroup, DeviceBackupResult
from backups.models import Backup, StoredBackup
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
    BackupSerializer, DeviceBackupResultWithStorageSerializer, RetentionPolicySerializer, BackupLocationSerializer,
    CredentialSerializer, CredentialTypeSerializer, CollectionGroupSerializer,
    UserSerializer, AuditLogSerializer,
    LoginSerializer, UserUpdateSerializer, ChangePasswordSerializer, DashboardLayoutSerializer,
    UserProfileSerializer, BackupScheduleSerializer, GroupSerializer,
    DeviceGroupSerializer, DeviceGroupRoleSerializer, DeviceGroupPermissionSerializer,
    UserDeviceGroupRoleSerializer, GroupDeviceGroupRoleSerializer, DeviceDetailedSerializer
)
import json
from celery_app import app as celery_app
from devicevault_worker import collection_queue_name_from_group
import difflib, os

class DeviceTypeViewSet(viewsets.ModelViewSet):
    queryset = DeviceType.objects.all()
    serializer_class = DeviceTypeSerializer


class ManufacturerViewSet(viewsets.ModelViewSet):
    queryset = Manufacturer.objects.all()
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
    permission_classes = [IsAuthenticated]
    
    def check_permissions(self, request):
        """Override to enforce superuser-only access"""
        super().check_permissions(request)
        if not (request.user.is_staff or request.user.is_superuser):
            self.permission_denied(request, message="Only superusers can manage collection groups")
    
    def perform_destroy(self, instance):
        """Prevent deletion if any devices are assigned to this collection group"""
        if instance.device_count > 0:
            from django.core.exceptions import ValidationError
            raise ValidationError(f'Cannot delete collection group "{instance.name}": {instance.device_count} device(s) are assigned to this group.')
        instance.delete()



class BackupMethodViewSet(viewsets.ReadOnlyModelViewSet):
    """
    Read-only ViewSet for listing available backup method plugins
    
    Returns all plugins discovered under backups.plugins with their
    friendly_name, description, and is_binary flag.
    """
    permission_classes = [IsAuthenticated]
    
    def list(self, request):
        from backups.plugins import list_plugins
        plugins = list_plugins()
        data = [
            {
                'key': p.key,
                'friendly_name': p.friendly_name,
                'description': p.description,
                'is_binary': p.is_binary
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
        """Filter devices based on user's Django permissions for device groups and annotate last successful backup."""
        from devices.permissions import user_get_accessible_device_groups

        latest_success = DeviceBackupResult.objects.filter(
            device=OuterRef('pk'),
            status='success'
        ).order_by('-timestamp')

        annotated = Device.objects.annotate(
            last_success_time=Subquery(latest_success.values('timestamp')[:1]),
            last_success_status=Subquery(latest_success.values('status')[:1]),
        )

        user = self.request.user
        if user.is_staff or user.is_superuser:
            return annotated

        accessible_groups = user_get_accessible_device_groups(user)
        return annotated.filter(device_group__in=accessible_groups)
    
    def perform_destroy(self, instance):
        """Check delete permission before deleting"""
        from devices.permissions import user_has_device_group_permission
        
        if not self.request.user.is_staff and not self.request.user.is_superuser:
            if not instance.device_group:
                raise serializers.ValidationError("Device has no device group")
            
            if not user_has_device_group_permission(self.request.user, instance.device_group, 'delete_device'):
                raise serializers.ValidationError("You do not have permission to delete devices in this group")

    @decorators.action(detail=True, methods=['post'])
    def backup_now(self, request, pk=None):
        """Trigger an immediate backup for a device if user has the group's Django 'backup_now' permission"""
        device = self.get_object()
        if not device.device_group:
            return response.Response({ 'error': 'Device has no device group' }, status=status.HTTP_400_BAD_REQUEST)
        from devices.permissions import user_has_device_group_django_permission
        if not user_has_device_group_django_permission(request.user, device.device_group, 'backup_now'):
            return response.Response({ 'error': 'Not authorized for Backup Now on this device group' }, status=status.HTTP_403_FORBIDDEN)

        # Enqueue backup task via Celery (orchestrator workers will perform the work)
        cfg = {
            'device_id': device.id,
            'task_identifier': f'backup_now:{device.id}:{timezone.now().isoformat()}',
            'ip': device.ip_address,
            'credentials': device.credential.data if device.credential else {},
            'backup_method': device.backup_method,
            'plugin_params': {},
            'timeout': 240
        }

        queue = None
        if device.collection_group:
            queue_name = collection_queue_name_from_group(device.collection_group)
            if queue_name:
                queue = queue_name

        try:
            task = celery_app.send_task('device.collect', args=[json.dumps(cfg)], queue=queue)
            return response.Response({'task_id': task.id, 'queued_on': queue}, status=status.HTTP_202_ACCEPTED)
        except Exception as exc:
            return response.Response({'error': str(exc)}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)

    @decorators.action(detail=True, methods=['post'])
    def collect(self, request, pk=None):
        """Enqueue a collection task for this device.

        Routing: If device.collection_group is set, the task will be queued to
        the group's queue (collector.group.<rabbitmq_queue_id>); otherwise the
        default broker routing will be used.
        """
        device = self.get_object()
        # Permission check - reuse existing RBAC for 'backup_now'
        from devices.permissions import user_has_device_group_django_permission
        if device.device_group and not user_has_device_group_django_permission(request.user, device.device_group, 'backup_now') and not request.user.is_superuser:
            return response.Response({'error': 'Not authorized to start backup for this device'}, status=status.HTTP_403_FORBIDDEN)

        cfg = {
            'device_id': device.id,
            'task_identifier': f'collect:{device.id}:{timezone.now().isoformat()}',
            'ip': device.ip_address,
            'credentials': device.credential.data if device.credential else {},
            'backup_method': device.backup_method,
            'plugin_params': {},
            'timeout': 240
        }

        queue = None
        if device.collection_group:
            queue_name = collection_queue_name_from_group(device.collection_group)
            if queue_name:
                queue = queue_name

        # Use send_task to set routing dynamically
        try:
            task = celery_app.send_task('device.collect', args=[json.dumps(cfg)], queue=queue)
            return response.Response({'task_id': task.id, 'queued_on': queue}, status=status.HTTP_202_ACCEPTED)
        except Exception as exc:
            return response.Response({'error': str(exc)}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)
class BackupViewSet(viewsets.ModelViewSet):
    queryset = Backup.objects.all()
    serializer_class = BackupSerializer
    
    def get_queryset(self):
        """Filter backups to only those from accessible devices"""
        from devices.permissions import user_get_accessible_device_groups
        accessible_groups = user_get_accessible_device_groups(self.request.user)
        return Backup.objects.filter(device__device_group__in=accessible_groups)


class StoredBackupViewSet(viewsets.ReadOnlyModelViewSet):
    """Read-only ViewSet for backup results with optional storage linkage."""

    serializer_class = DeviceBackupResultWithStorageSerializer
    permission_classes = [IsAuthenticated]
    queryset = DeviceBackupResult.objects.none()

    def get_queryset(self):
        from devices.permissions import user_get_accessible_device_groups
        accessible_groups = user_get_accessible_device_groups(self.request.user)

        storage_qs = StoredBackup.objects.filter(
            task_identifier=OuterRef('task_identifier'),
            device_id=OuterRef('device_id'),
        ).order_by('-timestamp')

        qs = DeviceBackupResult.objects.filter(device__device_group__in=accessible_groups)

        device_id_param = self.request.query_params.get('device') or self.request.query_params.get('device_id')
        if device_id_param is not None:
            try:
                device_id = int(device_id_param)
            except (TypeError, ValueError):
                return qs.none()
            qs = qs.filter(device_id=device_id)

        qs = qs.annotate(
            storage_status=Subquery(storage_qs.values('status')[:1]),
            storage_backend=Subquery(storage_qs.values('storage_backend')[:1]),
            storage_ref=Subquery(storage_qs.values('storage_ref')[:1]),
            storage_timestamp=Subquery(storage_qs.values('timestamp')[:1]),
        ).select_related('device')

        return qs

    @decorators.action(detail=True, methods=['get'])
    def download(self, request, pk=None):
        """Synchronously retrieve backup content via storage worker (text or binary)."""
        backup_result = self.get_object()

        if not backup_result.device.device_group:
            return response.Response({'error': 'Device has no device group'}, status=status.HTTP_400_BAD_REQUEST)

        from devices.permissions import user_has_device_group_django_permission
        if not user_has_device_group_django_permission(request.user, backup_result.device.device_group, 'view_backups'):
            return response.Response({'error': 'Not authorized to view backups for this device group'}, status=status.HTTP_403_FORBIDDEN)

        storage_record = StoredBackup.objects.filter(
            device=backup_result.device,
            task_identifier=backup_result.task_identifier,
        ).order_by('-timestamp').first()

        if not storage_record:
            return response.Response({'error': 'No stored backup found for this task'}, status=status.HTTP_404_NOT_FOUND)

        if storage_record.status != 'success':
            return response.Response({'error': 'Storage not successful'}, status=status.HTTP_400_BAD_REQUEST)

        location = backup_result.device.backup_location
        if not location:
            return response.Response({'error': 'No backup location configured'}, status=status.HTTP_400_BAD_REQUEST)

        try:
            from backups.storage_client import read_backup_via_worker
            from backups.plugins import get_plugin
            import base64
            import io
            from django.http import FileResponse

            # Check if backup is binary by looking up the device's backup method plugin
            is_binary = False
            if backup_result.device and backup_result.device.backup_method:
                plugin = get_plugin(backup_result.device.backup_method)
                if plugin:
                    is_binary = plugin.is_binary
            
            result = read_backup_via_worker(
                storage_backend=storage_record.storage_backend,
                storage_ref=storage_record.storage_ref,
                storage_config=location.config or {},
                task_identifier=f'read:{storage_record.task_identifier}',
                is_binary=is_binary,
                timeout=60,
            )
            if result.get('status') != 'success':
                return response.Response(
                    {'error': 'Failed to read backup', 'log': result.get('log', [])},
                    status=status.HTTP_500_INTERNAL_SERVER_ERROR,
                )

            content = result.get('content') or ''
            
            if is_binary:
                # Binary backup: return file download
                # Content may be base64-encoded string; decode if necessary
                if isinstance(content, str):
                    try:
                        binary_data = base64.b64decode(content)
                    except Exception:
                        # If decode fails, encode string to bytes
                        binary_data = content.encode('latin-1')
                else:
                    binary_data = content
                
                timestamp_str = backup_result.timestamp.isoformat().replace(':', '-').replace('.', '_')
                filename = f"{backup_result.device.name}_{timestamp_str}.bin"
                
                return FileResponse(
                    io.BytesIO(binary_data),
                    filename=filename,
                    content_type='application/octet-stream'
                )
            else:
                # Text backup: return as text file download
                from django.http import HttpResponse
                resp = HttpResponse(content, content_type='text/plain')
                resp['Content-Disposition'] = f'attachment; filename="{backup_result.device.name}.cfg"'
                return resp
        except Exception as exc:
            return response.Response({'error': str(exc)}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)

    @decorators.action(detail=True, methods=['get'])
    def logs(self, request, pk=None):
        """Retrieve structured logs for a backup."""
        backup_result = self.get_object()

        if not backup_result.device.device_group:
            return response.Response({'error': 'Device has no device group'}, status=status.HTTP_400_BAD_REQUEST)

        from devices.permissions import user_has_device_group_django_permission
        if not user_has_device_group_django_permission(request.user, backup_result.device.device_group, 'view_backups'):
            return response.Response({'error': 'Not authorized to view backups for this device group'}, status=status.HTTP_403_FORBIDDEN)

        # Parse the log field (JSON array of log entries) from collection
        import json
        try:
            log_data = json.loads(backup_result.log) if backup_result.log else []
        except (json.JSONDecodeError, TypeError):
            log_data = []

        # Normalize log entries: support both string (legacy) and structured formats
        normalized_logs = []
        from backups.plugins import get_plugin
        plugin_key = backup_result.device.backup_method if backup_result.device else 'unknown'
        plugin = get_plugin(plugin_key) if plugin_key else None
        source_default = plugin.friendly_name if plugin else plugin_key

        for entry in log_data:
            if isinstance(entry, dict):
                # Already structured
                normalized_logs.append({
                    'source': entry.get('source', source_default),
                    'timestamp': entry.get('timestamp', backup_result.timestamp.isoformat() + 'Z'),
                    'severity': entry.get('severity', 'INFO'),
                    'message': entry.get('message', '')
                })
            elif isinstance(entry, str):
                # Legacy string format - convert to structured
                normalized_logs.append({
                    'source': source_default,
                    'timestamp': backup_result.timestamp.isoformat() + 'Z',
                    'severity': 'INFO',
                    'message': entry
                })

        # Also include storage logs if available
        storage_record = StoredBackup.objects.filter(
            device=backup_result.device,
            task_identifier=backup_result.task_identifier,
        ).order_by('-timestamp').first()

        if storage_record and storage_record.log:
            try:
                storage_log_data = json.loads(storage_record.log) if storage_record.log else []
            except (json.JSONDecodeError, TypeError):
                storage_log_data = []

            for entry in storage_log_data:
                if isinstance(entry, dict):
                    # Already structured
                    normalized_logs.append({
                        'source': entry.get('source', 'storage_worker'),
                        'timestamp': entry.get('timestamp', storage_record.timestamp.isoformat() + 'Z'),
                        'severity': entry.get('severity', 'INFO'),
                        'message': entry.get('message', '')
                    })
                elif isinstance(entry, str):
                    # Legacy string format - convert to structured
                    normalized_logs.append({
                        'source': 'storage_worker',
                        'timestamp': storage_record.timestamp.isoformat() + 'Z',
                        'severity': 'INFO',
                        'message': entry
                    })

        # Sort logs by timestamp to show chronological order
        normalized_logs.sort(key=lambda x: x['timestamp'])

        return response.Response({'logs': normalized_logs}, status=status.HTTP_200_OK)


@decorators.api_view(['GET'])
@decorators.permission_classes([IsAuthenticated])
def recent_backup_activity(request):
    """Get recent backup activity for devices user has access to"""
    from devices.permissions import user_get_accessible_device_groups
    from datetime import datetime, timedelta
    from django.utils import timezone
    
    accessible_groups = user_get_accessible_device_groups(request.user)
    user_devices = Device.objects.filter(device_group__in=accessible_groups)
    
    # Get time filter from query parameter (default: 1 hour)
    time_filter = request.GET.get('time_filter', '1h')
    
    # Calculate time threshold based on filter
    now = timezone.now()
    if time_filter == '1h':
        time_threshold = now - timedelta(hours=1)
        limit = int(request.GET.get('limit', 50))
    elif time_filter == '24h':
        time_threshold = now - timedelta(hours=24)
        limit = int(request.GET.get('limit', 100))
    elif time_filter == '7d':
        time_threshold = now - timedelta(days=7)
        limit = int(request.GET.get('limit', 200))
    else:
        # Default to 1 hour if invalid filter
        time_threshold = now - timedelta(hours=1)
        limit = int(request.GET.get('limit', 50))
    
    # Get recent backups from DeviceBackupResult (authoritative backup collection results)
    recent_backups = DeviceBackupResult.objects.filter(
        device__in=user_devices,
        timestamp__gte=time_threshold
    ).select_related('device', 'device__device_type').order_by('-timestamp')[:limit]
    
    activity = []
    for backup in recent_backups:
        # Determine storage status based on backup result and storage result
        storage_status = 'n/a'
        storage_status_display = 'N/A'
        
        if backup.status == 'success':
            # Backup was successful, check for storage result
            try:
                storage_result = StoredBackup.objects.filter(
                    task_identifier=backup.task_identifier
                ).first()
                if storage_result:
                    storage_status = storage_result.status
                    storage_status_display = storage_result.status.capitalize()
                else:
                    # No storage result yet, still pending
                    storage_status = 'pending'
                    storage_status_display = 'Pending'
            except Exception:
                storage_status = 'pending'
                storage_status_display = 'Pending'
        # If backup failed, storage_status stays as 'n/a'
        
        # Determine duration in seconds with 1 decimal place
        duration = None
        if backup.overall_duration_ms:
            duration = round(backup.overall_duration_ms / 1000, 1)
        
        activity.append({
            'id': backup.id,
            'task_identifier': backup.task_identifier,
            'device_name': backup.device.name,
            'device_type': backup.device.device_type.name if backup.device.device_type else 'Unknown',
            'timestamp': backup.timestamp.isoformat() if backup.timestamp else None,  # ISO format with UTC timezone
            'status': backup.status,
            'status_display': backup.status.capitalize(),
            'storage_status': storage_status,
            'storage_status_display': storage_status_display,
            'duration': duration,
            'log': backup.log
        })
    
    return response.Response(activity)

@decorators.api_view(['GET'])
def timezone_config(request):
    """Return the configured application timezone"""
    from core.timezone_utils import get_timezone_name
    return response.Response({
        'timezone': get_timezone_name()
    })
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
    from devices.permissions import user_get_accessible_device_groups
    from django.db.models import Max, Subquery, OuterRef, Avg
    from core.timezone_utils import get_time_bounds_24h, local_now, get_day_bounds_local, get_timezone_name
    
    # Get number of days for chart from query parameter (default 7)
    days = int(request.GET.get('days', 7))
    days = min(max(days, 1), 90)  # Limit between 1 and 90 days
    
    # Get time bounds in UTC for "last 24 hours" in local timezone
    yesterday_utc, now_utc = get_time_bounds_24h()
    
    # Filter devices by user's accessible device groups
    accessible_groups = user_get_accessible_device_groups(request.user)
    user_devices = Device.objects.filter(device_group__in=accessible_groups)
    
    device_count = user_devices.values('device_type__name', 'device_type__icon').annotate(count=Count('id'))
    
    # Backups in last 24h - count all DeviceBackupResult records
    # Success: those that have successful collection
    backup_results_24h = DeviceBackupResult.objects.filter(
        device__in=user_devices,
        timestamp__gte=yesterday_utc
    )
    
    # Successful backups (collection succeeded)
    success_24h = backup_results_24h.filter(status='success').count()
    
    # Failed backups: collection failures + storage failures
    # Collection failures - backups that failed during collection (status can be 'failed' or 'failure')
    collection_failures = backup_results_24h.filter(status__in=['failed', 'failure']).count()
    
    # Storage failures - successful collections that failed to store
    # Get task_identifiers of successful backups
    successful_task_ids = list(backup_results_24h.filter(status='success').values_list('task_identifier', flat=True))
    storage_failures = StoredBackup.objects.filter(
        task_identifier__in=successful_task_ids,
        timestamp__gte=yesterday_utc,
        status__in=['failed', 'failure']
    ).count() if successful_task_ids else 0
    
    failed_24h = collection_failures + storage_failures
    
    # In Progress: successful backups without storage result yet
    stored_task_ids = list(StoredBackup.objects.filter(
        task_identifier__in=successful_task_ids,
        timestamp__gte=yesterday_utc
    ).values_list('task_identifier', flat=True)) if successful_task_ids else []
    in_progress_24h = len(set(successful_task_ids) - set(stored_task_ids))
    
    # Average overall backup time - calculate from DeviceBackupResult for last 24h
    # overall_duration_ms is the total time from initiation to completion (step 1 to 5 or 9)
    avg_result = DeviceBackupResult.objects.filter(
        device__in=user_devices,
        timestamp__gte=yesterday_utc,
        overall_duration_ms__isnull=False
    ).aggregate(avg_ms=Avg('overall_duration_ms'))
    
    # Convert from milliseconds to seconds with 1 decimal place
    avg_duration_ms = avg_result.get('avg_ms') or 0
    avg_duration = round(avg_duration_ms / 1000, 1) if avg_duration_ms else 0.0
    
    # Success rate - based on most recent backup per device
    total_devices = user_devices.count()
    
    # Get the most recent backup per device using StoredBackup
    latest_backups = StoredBackup.objects.filter(
        device=OuterRef('pk')
    ).order_by('-timestamp')
    
    devices_with_latest = user_devices.annotate(
        latest_backup_id=Subquery(latest_backups.values('id')[:1]),
        latest_backup_status=Subquery(latest_backups.values('status')[:1])
    )
    
    successful_devices = devices_with_latest.filter(latest_backup_status='success').count()
    success_rate_percent = (successful_devices / total_devices * 100) if total_devices > 0 else 0
    
    # Get daily backup stats for chart using local timezone day boundaries
    daily_stats = []
    local_today = local_now().date()
    for i in range(days):
        day_offset = days - 1 - i
        target_date = local_today - timedelta(days=day_offset)
        day_start_utc, day_end_utc = get_day_bounds_local(target_date)
        
        success = StoredBackup.objects.filter(
            device__in=user_devices,
            timestamp__gte=day_start_utc, 
            timestamp__lt=day_end_utc, 
            status='success'
        ).count()
        failed = StoredBackup.objects.filter(
            device__in=user_devices,
            timestamp__gte=day_start_utc, 
            timestamp__lt=day_end_utc, 
            status__in=['failed', 'failure']
        ).count()
        total = success + failed
        daily_stats.append({
            'date': target_date.strftime('%Y-%m-%d'),
            'success': success,
            'failed': failed,
            'rate': (success / total * 100) if total > 0 else 0
        })
    
    return response.Response({
        'devicesByType': dict((item['device_type__name'], {'count': item['count'], 'icon': item['device_type__icon']}) for item in device_count),
        'success24h': success_24h,
        'failed24h': failed_24h,
        'inProgress24h': in_progress_24h,
        'avgDuration': avg_duration,
        'successRate': round(success_rate_percent, 1),
        'dailyStats': daily_stats,
        'timezone': get_timezone_name()  # Include timezone info for frontend
    })

class AuthConfigView(APIView):
    permission_classes = [AllowAny]
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
    permission_classes = [IsAdminUser]
    
    def get_queryset(self):
        """Return Django auth permissions with dg_ prefix"""
        return Permission.objects.filter(codename__startswith='dg_').order_by('codename')
    
    def list(self, request, *args, **kwargs):
        """Return simplified permission list"""
        queryset = self.get_queryset()
        data = [
            {
                'id': p.id,
                'codename': p.codename,
                'name': p.name
            }
            for p in queryset
        ]
        return response.Response(data)
    
    def retrieve(self, request, pk=None, *args, **kwargs):
        """Return single permission details"""
        try:
            permission = Permission.objects.get(pk=pk, codename__startswith='dg_')
            data = {
                'id': permission.id,
                'codename': permission.codename,
                'name': permission.name
            }
            return response.Response(data)
        except Permission.DoesNotExist:
            return response.Response(
                {'error': 'Permission not found'},
                status=status.HTTP_404_NOT_FOUND
            )


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


class ScheduledBackupsCalendarView(APIView):
    """
    API View for scheduled backups calendar data
    
    GET: Return upcoming scheduled backups for the next 30 days
    Filters devices by user's device group permissions
    """
    permission_classes = [IsAuthenticated]
    
    def get(self, request):
        """
        Retrieve upcoming scheduled backups grouped by date and schedule
        
        Returns:
            {
                "2026-01-15": [
                    {
                        "schedule_id": 1,
                        "schedule_name": "Daily 2 AM",
                        "time": "02:00",
                        "device_count": 5,
                        "devices": [
                            {"id": 1, "name": "router-1", "ip_address": "10.0.0.1"},
                            ...
                        ]
                    },
                    ...
                ],
                "2026-01-16": [...],
                ...
            }
        """
        from devices.permissions import user_get_accessible_device_groups
        from core.timezone_utils import get_display_timezone, utc_to_local, local_to_utc
        from datetime import datetime, timedelta
        
        try:
            # Get user's accessible device groups
            user = request.user
            if user.is_staff or user.is_superuser:
                accessible_groups = DeviceGroup.objects.all()
            else:
                accessible_groups = user_get_accessible_device_groups(user)
            
            # Calculate 30-day window
            now_utc = timezone.now()
            end_date_utc = now_utc + timedelta(days=30)
            display_tz = get_display_timezone()
            
            # Get all enabled schedules with devices
            schedules = BackupSchedule.objects.filter(enabled=True).prefetch_related(
                Prefetch(
                    'device_set',
                    Device.objects.filter(
                        enabled=True,
                        device_group__in=accessible_groups
                    ).select_related('device_group')
                )
            )
            
            # Build calendar data structure
            calendar_data = {}
            
            for schedule in schedules:
                devices = schedule.device_set.all()
                if not devices.exists():
                    continue
                
                # Calculate all occurrences of this schedule in the 30-day window
                check_time = now_utc
                loop_count = 0
                while check_time < end_date_utc:
                    loop_count += 1
                    # Calculate next run from check_time
                    from backups.scheduler import SchedulerDaemon
                    scheduler = SchedulerDaemon()
                    next_run_display = scheduler.calculate_next_run(schedule, check_time)
                    next_run_utc = local_to_utc(next_run_display)
                    
                    if next_run_utc >= end_date_utc:
                        break
                    
                    # Format date string for calendar
                    date_display = utc_to_local(next_run_utc)
                    date_str = date_display.strftime('%Y-%m-%d')
                    time_str = date_display.strftime('%H:%M')
                    
                    if date_str not in calendar_data:
                        calendar_data[date_str] = []
                    
                    # Create entry for this schedule occurrence
                    entry = {
                        'schedule_id': schedule.id,
                        'schedule_name': schedule.name,
                        'time': time_str,
                        'device_count': devices.count(),
                        'devices': [
                            {
                                'id': d.id,
                                'name': d.name,
                                'ip_address': d.ip_address,
                                'device_group': d.device_group.name if d.device_group else None
                            }
                            for d in devices
                        ]
                    }
                    calendar_data[date_str].append(entry)
                    
                    # Move to next interval
                    check_time = next_run_utc + timedelta(seconds=1)
                    
                    # Safety: don't calculate more than 365 days worth
                    if (end_date_utc - check_time).days > 365:
                        break
            
            return response.Response(calendar_data)
        
        except Exception as exc:
            import logging
            logger = logging.getLogger(__name__)
            logger.exception("Error in scheduled backups calendar view")
            return response.Response(
                {'error': 'Failed to retrieve scheduled backups'},
                status=status.HTTP_500_INTERNAL_SERVER_ERROR
            )


class ThemeSettingsView(APIView):
    """
    API View for theme settings (superuser only for updates)
    
    GET: Public access to retrieve theme settings
    PUT: Superuser only to update theme settings
    """
    permission_classes = [AllowAny]
    
    def get(self, request):
        """Retrieve current theme settings"""
        from core.theme_settings import ThemeSettings
        from api.serializers import ThemeSettingsSerializer
        
        settings = ThemeSettings.load()
        serializer = ThemeSettingsSerializer(settings)
        return response.Response(serializer.data)
    
    def put(self, request):
        """Update theme settings (superuser only)"""
        from core.theme_settings import ThemeSettings
        from api.serializers import ThemeSettingsSerializer
        
        if not request.user.is_authenticated:
            return response.Response(
                {'error': 'Authentication required'},
                status=status.HTTP_401_UNAUTHORIZED
            )
        
        if not request.user.is_superuser:
            return response.Response(
                {'error': 'Only superusers can modify theme settings'},
                status=status.HTTP_403_FORBIDDEN
            )
        
        settings = ThemeSettings.load()
        serializer = ThemeSettingsSerializer(settings, data=request.data, partial=True)
        
        if serializer.is_valid():
            serializer.save()
            return response.Response(serializer.data)
        
        return response.Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)
