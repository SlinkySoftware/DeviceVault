
from rest_framework import serializers
from devices.models import DeviceType, Manufacturer, Device
from backups.models import Backup
from policies.models import RetentionPolicy
from locations.models import BackupLocation
from credentials.models import Credential, CredentialType
from core.models import Label
from rbac.models import Role, Permission
from audit.models import AuditLog
from django.contrib.auth.models import User
from django.contrib.auth import authenticate
from django.contrib.auth import authenticate

class DeviceTypeSerializer(serializers.ModelSerializer):
    class Meta: model = DeviceType; fields='__all__'
class ManufacturerSerializer(serializers.ModelSerializer):
    class Meta: model = Manufacturer; fields='__all__'
class LabelSerializer(serializers.ModelSerializer):
    class Meta: model = Label; fields='__all__'
class RetentionPolicySerializer(serializers.ModelSerializer):
    class Meta: model = RetentionPolicy; fields='__all__'
class BackupLocationSerializer(serializers.ModelSerializer):
    class Meta: model = BackupLocation; fields='__all__'
class CredentialTypeSerializer(serializers.ModelSerializer):
    class Meta: model = CredentialType; fields='__all__'
class CredentialSerializer(serializers.ModelSerializer):
    class Meta: model = Credential; fields='__all__'
class DeviceSerializer(serializers.ModelSerializer):
    class Meta: model = Device; fields='__all__'
class BackupSerializer(serializers.ModelSerializer):
    class Meta: model = Backup; fields='__all__'
class PermissionSerializer(serializers.ModelSerializer):
    class Meta: model = Permission; fields='__all__'
class RoleSerializer(serializers.ModelSerializer):
    class Meta: model = Role; fields='__all__'
class UserSerializer(serializers.ModelSerializer):
    is_jit = serializers.SerializerMethodField(read_only=True)

    class Meta:
        model = User
        fields = ['id','username','email','first_name','last_name','is_jit']

    def get_is_jit(self, obj):
        try:
            has_social = hasattr(obj, 'social_auth') and obj.social_auth.exists()
        except Exception:
            has_social = False
        return (not obj.has_usable_password()) or has_social
class AuditLogSerializer(serializers.ModelSerializer):
    actor_name = serializers.CharField(source='actor.username', read_only=True)
    class Meta: model = AuditLog; fields='__all__'

# Authentication Serializers
class LoginSerializer(serializers.Serializer):
    username = serializers.CharField(write_only=True)
    password = serializers.CharField(write_only=True, style={'input_type': 'password'})

    def validate(self, data):
        user = authenticate(username=data['username'], password=data['password'])
        if not user:
            raise serializers.ValidationError('Invalid credentials')
        data['user'] = user
        return data

# User update serializer for editable fields
class UserUpdateSerializer(serializers.ModelSerializer):
    class Meta:
        model = User
        fields = ['email', 'first_name', 'last_name']
        extra_kwargs = {
            'email': {'required': False},
            'first_name': {'required': False},
            'last_name': {'required': False}
        }

class ChangePasswordSerializer(serializers.Serializer):
    current_password = serializers.CharField(write_only=True, style={'input_type': 'password'})
    new_password = serializers.CharField(write_only=True, style={'input_type': 'password'})

    def validate(self, data):
        user = self.context['request'].user
        # Block for JIT/SSO users
        try:
            has_social = hasattr(user, 'social_auth') and user.social_auth.exists()
        except Exception:
            has_social = False
        if (not user.has_usable_password()) or has_social:
            raise serializers.ValidationError('Password is managed by external identity provider and cannot be changed.')
        if not user.check_password(data['current_password']):
            raise serializers.ValidationError({'current_password': 'Current password is incorrect'})
        if len(data['new_password']) < 8:
            raise serializers.ValidationError({'new_password': 'New password must be at least 8 characters'})
        return data

# Dashboard Layout Serializer
from core.models import DashboardLayout, UserProfile

class DashboardLayoutSerializer(serializers.ModelSerializer):
    class Meta:
        model = DashboardLayout
        fields = ['id', 'user', 'is_default', 'layout', 'updated_at']

class UserProfileSerializer(serializers.ModelSerializer):
    class Meta:
        model = UserProfile
        fields = ['theme', 'created_at', 'updated_at']
