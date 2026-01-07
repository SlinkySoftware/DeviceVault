"""
Django REST Framework Serializers
Converts database models to/from JSON for API requests and responses.
Includes authentication serializers for login and user profile management.
"""

from rest_framework import serializers
from devices.models import DeviceType, Manufacturer, Device
from backups.models import Backup
from policies.models import RetentionPolicy, BackupSchedule
from locations.models import BackupLocation
from credentials.models import Credential, CredentialType
from core.models import Label
from rbac.models import Role, Permission
from audit.models import AuditLog
from django.contrib.auth.models import User
from django.contrib.auth import authenticate


# ===== Model Serializers (Standard CRUD) =====

class DeviceTypeSerializer(serializers.ModelSerializer):
    """Serializes DeviceType model for API responses"""
    class Meta:
        model = DeviceType
        fields = '__all__'


class ManufacturerSerializer(serializers.ModelSerializer):
    """Serializes Manufacturer model for API responses"""
    class Meta:
        model = Manufacturer
        fields = '__all__'


class LabelSerializer(serializers.ModelSerializer):
    """Serializes Label model for API responses"""
    class Meta:
        model = Label
        fields = '__all__'


class RetentionPolicySerializer(serializers.ModelSerializer):
    """Serializes RetentionPolicy model for API responses"""
    class Meta:
        model = RetentionPolicy
        fields = '__all__'


class BackupScheduleSerializer(serializers.ModelSerializer):
    """
    Serializes BackupSchedule model for API responses
    Used by Celery Beat to configure automated backup scheduling
    """
    class Meta:
        model = BackupSchedule
        fields = '__all__'


class BackupLocationSerializer(serializers.ModelSerializer):
    """Serializes BackupLocation model for API responses"""
    class Meta:
        model = BackupLocation
        fields = '__all__'


class CredentialTypeSerializer(serializers.ModelSerializer):
    """Serializes CredentialType model for API responses"""
    class Meta:
        model = CredentialType
        fields = '__all__'


class CredentialSerializer(serializers.ModelSerializer):
    """Serializes Credential model for API responses"""
    class Meta:
        model = Credential
        fields = '__all__'


class DeviceSerializer(serializers.ModelSerializer):
    """
    Serializes Device model with nested related objects
    
    Nested Objects:
        - device_type (DeviceTypeSerializer): Includes icon and name
        - manufacturer (ManufacturerSerializer): Full manufacturer details
    """
    device_type = DeviceTypeSerializer(read_only=True)
    manufacturer = ManufacturerSerializer(read_only=True)
    
    class Meta:
        model = Device
        fields = '__all__'


class BackupSerializer(serializers.ModelSerializer):
    """Serializes Backup model for API responses"""
    class Meta:
        model = Backup
        fields = '__all__'


class PermissionSerializer(serializers.ModelSerializer):
    """Serializes Permission model for API responses"""
    class Meta:
        model = Permission
        fields = '__all__'


class RoleSerializer(serializers.ModelSerializer):
    """Serializes Role model for API responses"""
    class Meta:
        model = Role
        fields = '__all__'


class UserSerializer(serializers.ModelSerializer):
    """
    Serializes User model with JIT detection
    
    Fields:
        - id, username, email, first_name, last_name (from User model)
        - is_jit (computed): Whether user is from SSO/LDAP (Just-In-Time provisioned)
    
    Methods:
        - get_is_jit(obj): Determines if user is from external identity provider
    """
    is_jit = serializers.SerializerMethodField(read_only=True)

    class Meta:
        model = User
        fields = ['id', 'username', 'email', 'first_name', 'last_name', 'is_jit']

    def get_is_jit(self, obj):
        """
        Detect if user is from Just-In-Time provisioning (SSO/LDAP)
        
        Args:
            obj (User): User instance to check
            
        Returns:
            bool: True if user has no usable password or has social auth relation
        """
        try:
            has_social = hasattr(obj, 'social_auth') and obj.social_auth.exists()
        except Exception:
            has_social = False
        return (not obj.has_usable_password()) or has_social


class AuditLogSerializer(serializers.ModelSerializer):
    """
    Serializes AuditLog model with actor name resolution
    
    Fields:
        - actor_name (computed): Username of the user who triggered the action
    """
    actor_name = serializers.CharField(source='actor.username', read_only=True)
    
    class Meta:
        model = AuditLog
        fields = '__all__'


# ===== Authentication Serializers =====

class LoginSerializer(serializers.Serializer):
    """
    Validates login credentials and authenticates user
    
    Inputs:
        - username (str): Username or email
        - password (str): User password
    
    Outputs (if valid):
        - user (User): Authenticated user instance
    
    Raises:
        ValidationError: If credentials are invalid
    """
    username = serializers.CharField(write_only=True, help_text='Username or email address')
    password = serializers.CharField(write_only=True, style={'input_type': 'password'}, help_text='User password')

    def validate(self, data):
        """
        Authenticate user against provided credentials
        
        Args:
            data (dict): username and password from request
            
        Returns:
            dict: Validated data with authenticated user instance
            
        Raises:
            ValidationError: If authentication fails
        """
        user = authenticate(username=data['username'], password=data['password'])
        if not user:
            raise serializers.ValidationError('Invalid credentials')
        data['user'] = user
        return data


# ===== User Profile Serializers =====

class UserUpdateSerializer(serializers.ModelSerializer):
    """
    Serializer for updating editable user profile fields
    
    Editable Fields:
        - email: User email address
        - first_name: User's first name
        - last_name: User's last name
    
    Note: Username and password are not editable via this serializer
    """
    class Meta:
        model = User
        fields = ['email', 'first_name', 'last_name']
        extra_kwargs = {
            'email': {'required': False},
            'first_name': {'required': False},
            'last_name': {'required': False}
        }


class ChangePasswordSerializer(serializers.Serializer):
    """
    Validates password change request for local users
    
    Inputs:
        - current_password (str): User's current password
        - new_password (str): New password (min 8 characters)
    
    Restrictions:
        - Cannot change password if user is from SSO/LDAP (JIT provisioned)
        - Current password must match existing password
        - New password must be at least 8 characters
    """
    current_password = serializers.CharField(write_only=True, style={'input_type': 'password'}, help_text='Current password for verification')
    new_password = serializers.CharField(write_only=True, style={'input_type': 'password'}, help_text='New password (minimum 8 characters)')

    def validate(self, data):
        """
        Validate password change request
        
        Args:
            data (dict): current_password and new_password from request
            
        Returns:
            dict: Validated password data
            
        Raises:
            ValidationError: If validation fails (JIT user, wrong current password, weak password)
        """
        user = self.context['request'].user
        # Block password changes for JIT/SSO users
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

from core.models import DashboardLayout, UserProfile

class DashboardLayoutSerializer(serializers.ModelSerializer):
    class Meta:
        model = DashboardLayout
        fields = ['id', 'user', 'is_default', 'layout', 'updated_at']

class UserProfileSerializer(serializers.ModelSerializer):
    class Meta:
        model = UserProfile
        fields = ['theme', 'created_at', 'updated_at']
