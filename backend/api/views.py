
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
from policies.models import RetentionPolicy
from locations.models import BackupLocation
from credentials.models import Credential, CredentialType
from core.models import Label
from rbac.models import Role, Permission
from audit.models import AuditLog
from .serializers import (
    DeviceTypeSerializer, ManufacturerSerializer, DeviceSerializer,
    BackupSerializer, RetentionPolicySerializer, BackupLocationSerializer,
    CredentialSerializer, CredentialTypeSerializer, LabelSerializer,
    RoleSerializer, PermissionSerializer, UserSerializer, AuditLogSerializer,
    LoginSerializer, UserUpdateSerializer, ChangePasswordSerializer
)
import difflib, os

class DeviceTypeViewSet(viewsets.ModelViewSet):
    queryset = DeviceType.objects.all()
    serializer_class = DeviceTypeSerializer
class ManufacturerViewSet(viewsets.ModelViewSet):
    queryset = Manufacturer.objects.all()
    serializer_class = ManufacturerSerializer
class DeviceViewSet(viewsets.ModelViewSet):
    queryset = Device.objects.all()
    serializer_class = DeviceSerializer
class BackupViewSet(viewsets.ModelViewSet):
    queryset = Backup.objects.all()
    serializer_class = BackupSerializer
class RetentionPolicyViewSet(viewsets.ModelViewSet):
    queryset = RetentionPolicy.objects.all()
    serializer_class = RetentionPolicySerializer
class BackupLocationViewSet(viewsets.ModelViewSet):
    queryset = BackupLocation.objects.all()
    serializer_class = BackupLocationSerializer
class CredentialViewSet(viewsets.ModelViewSet):
    queryset = Credential.objects.all()
    serializer_class = CredentialSerializer
class CredentialTypeViewSet(viewsets.ModelViewSet):
    queryset = CredentialType.objects.all()
    serializer_class = CredentialTypeSerializer
class LabelViewSet(viewsets.ModelViewSet):
    queryset = Label.objects.all()
    serializer_class = LabelSerializer
class RoleViewSet(viewsets.ModelViewSet):
    queryset = Role.objects.all()
    serializer_class = RoleSerializer
class PermissionViewSet(viewsets.ModelViewSet):
    queryset = Permission.objects.all()
    serializer_class = PermissionSerializer
class UserViewSet(viewsets.ReadOnlyModelViewSet):
    queryset = User.objects.all()
    serializer_class = UserSerializer

    def _is_jit_provisioned(self, user):
        try:
            has_social = hasattr(user, 'social_auth') and user.social_auth.exists()
        except Exception:
            has_social = False
        return (not user.has_usable_password()) or has_social

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
        return response.Response({'providers': ['LDAP','SAML','EntraID','Local']})

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
        return response.Response({
            **serializer.data,
            'editable': editable
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

@decorators.api_view(['POST'])
def compare_backups(request):
    a = request.data.get('a_path'); b = request.data.get('b_path')
    if not (a and b and os.path.exists(a) and os.path.exists(b)):
        return response.Response({'error':'invalid paths'}, status=status.HTTP_400_BAD_REQUEST)
    with open(a) as fa, open(b) as fb:
        a_text = fa.read().splitlines(); b_text = fb.read().splitlines()
    diff = difflib.unified_diff(a_text, b_text, fromfile=a, tofile=b, lineterm='')
    return response.Response({'diff':''.join(list(diff))})
