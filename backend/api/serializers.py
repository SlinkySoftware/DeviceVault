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
from devices.models import (
    DeviceGroup, DeviceGroupRole, DeviceGroupPermission,
    UserDeviceGroupRole, GroupDeviceGroupRole
)
from audit.models import AuditLog
from django.contrib.auth.models import User, Group
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
        - manufacturer (ManufacturerSerializer): Full manufacturer details (optional)
        - user_permissions (SerializerMethodField): User's permissions for device's group
    """
    device_type = DeviceTypeSerializer(read_only=True)
    manufacturer = ManufacturerSerializer(read_only=True)
    user_permissions = serializers.SerializerMethodField()
    device_group_name = serializers.CharField(source='device_group.name', read_only=True)
    backup_method_display = serializers.SerializerMethodField()
    
    class Meta:
        model = Device
        fields = '__all__'
    
    def get_user_permissions(self, obj):
        """Get permissions for the requesting user for this device's group"""
        from devices.permissions import user_get_device_group_permissions
        
        request = self.context.get('request')
        if not request or not request.user:
            return []
        
        if not obj.device_group:
            return []
        
        permissions = user_get_device_group_permissions(request.user, obj.device_group)
        return list(permissions)
    
    def get_backup_method_display(self, obj):
        """Get friendly name of backup method plugin"""
        from backups.plugins import get_plugin
        plugin = get_plugin(obj.backup_method)
        return plugin.friendly_name if plugin else obj.backup_method
    
    def get_backup_method_display(self, obj):
        """Get friendly name of backup method plugin"""
        from backups.plugins import get_plugin
        plugin = get_plugin(obj.backup_method)
        return plugin.friendly_name if plugin else obj.backup_method


class BackupSerializer(serializers.ModelSerializer):
    """Serializes Backup model for API responses"""
    class Meta:
        model = Backup
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
    password = serializers.CharField(write_only=True, required=False, allow_blank=True)

    class Meta:
        model = User
        fields = ['id', 'username', 'email', 'first_name', 'last_name', 'is_staff', 'is_superuser', 'is_jit', 'password']

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
    
    def create(self, validated_data):
        """Create a new user with password"""
        password = validated_data.pop('password', None)
        user = User.objects.create(**validated_data)
        if password:
            user.set_password(password)
            user.save()
        return user


class GroupSerializer(serializers.ModelSerializer):
    """
    Serializes Django auth Group with user membership and device group role assignments.

    Read-only:
        - users: Users in this group
        - device_group_roles: Device group roles assigned to this group

    Write-only:
        - user_ids: List of user IDs to set as group members
        - device_group_role_ids: List of device group role IDs to assign
    """
    users = serializers.SerializerMethodField(read_only=True)
    device_group_roles = serializers.SerializerMethodField(read_only=True)
    user_ids = serializers.ListField(child=serializers.IntegerField(), write_only=True, required=False)
    device_group_role_ids = serializers.ListField(child=serializers.IntegerField(), write_only=True, required=False)

    class Meta:
        model = Group
        fields = ['id', 'name', 'users', 'device_group_roles', 'user_ids', 'device_group_role_ids']

    def get_users(self, obj):
        return UserSerializer(obj.user_set.all(), many=True).data

    def get_device_group_roles(self, obj):
        qs = GroupDeviceGroupRole.objects.filter(auth_group=obj).select_related('role')
        roles = [g.role for g in qs]
        return DeviceGroupRoleSerializer(roles, many=True).data

    def create(self, validated_data):
        user_ids = validated_data.pop('user_ids', [])
        device_group_role_ids = validated_data.pop('device_group_role_ids', [])
        group = Group.objects.create(name=validated_data.get('name'))
        self._set_users(group, user_ids)
        self._set_device_group_roles(group, device_group_role_ids)
        return group

    def update(self, instance, validated_data):
        user_ids = validated_data.pop('user_ids', None)
        device_group_role_ids = validated_data.pop('device_group_role_ids', None)
        name = validated_data.get('name')
        if name is not None:
            instance.name = name
            instance.save()
        if user_ids is not None:
            instance.user_set.clear()
            if user_ids:
                users = User.objects.filter(id__in=user_ids)
                for u in users:
                    u.groups.add(instance)
        if device_group_role_ids is not None:
            GroupDeviceGroupRole.objects.filter(auth_group=instance).delete()
            self._set_device_group_roles(instance, device_group_role_ids)
        return instance

    def _set_users(self, group, user_ids):
        if user_ids:
            users = User.objects.filter(id__in=user_ids)
            for u in users:
                u.groups.add(group)

    def _set_device_group_roles(self, group, role_ids):
        if role_ids:
            roles = DeviceGroupRole.objects.filter(id__in=role_ids)
            for role in roles:
                GroupDeviceGroupRole.objects.get_or_create(auth_group=group, role=role)


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

# ===== Device Group RBAC Serializers =====

class DeviceGroupPermissionSerializer(serializers.ModelSerializer):
    """Serializes DeviceGroupPermission model for API responses"""
    class Meta:
        model = DeviceGroupPermission
        fields = ['id', 'code', 'description']


class DeviceGroupRoleSerializer(serializers.ModelSerializer):
    """Serializes DeviceGroupRole model with nested permissions"""
    permissions = DeviceGroupPermissionSerializer(many=True, read_only=True)
    device_group_name = serializers.CharField(source='device_group.name', read_only=True)
    
    class Meta:
        model = DeviceGroupRole
        fields = ['id', 'name', 'device_group', 'device_group_name', 'permissions', 'created_at']


class DeviceGroupSerializer(serializers.ModelSerializer):
    """Serializes DeviceGroup model with nested roles and user-level modify flag"""
    roles = DeviceGroupRoleSerializer(many=True, read_only=True)
    can_modify = serializers.SerializerMethodField()

    class Meta:
        model = DeviceGroup
        fields = ['id', 'name', 'description', 'roles', 'created_at', 'updated_at', 'can_modify']

    def get_can_modify(self, obj):
        """Return True if the requesting user has the group's Django modify permission"""
        request = self.context.get('request')
        if not request:
            return False
        user = request.user
        if not user or not user.is_authenticated:
            return False
        if user.is_staff or user.is_superuser:
            return True
        try:
            link = obj.django_permissions
        except Exception:
            return False
        perm = link.perm_modify
        perm_code = f"{perm.content_type.app_label}.{perm.codename}"
        return user.has_perm(perm_code)


class UserDeviceGroupRoleSerializer(serializers.ModelSerializer):
    """Serializes user-device group role assignments"""
    role = DeviceGroupRoleSerializer(read_only=True)
    username = serializers.CharField(source='user.username', read_only=True)
    
    class Meta:
        model = UserDeviceGroupRole
        fields = ['id', 'user', 'username', 'role']


class GroupDeviceGroupRoleSerializer(serializers.ModelSerializer):
    """Serializes auth group-device group role assignments"""
    role = DeviceGroupRoleSerializer(read_only=True)
    auth_group_name = serializers.CharField(source='auth_group.name', read_only=True)
    
    class Meta:
        model = GroupDeviceGroupRole
        fields = ['id', 'auth_group', 'auth_group_name', 'role']


class DeviceDetailedSerializer(serializers.ModelSerializer):
    """
    Serializes Device model with nested related objects and RBAC info
    
    Nested Objects:
        - device_type (DeviceTypeSerializer): Includes icon and name
        - manufacturer (ManufacturerSerializer): Full manufacturer details
        - device_group (DeviceGroupSerializer): Device group with roles
    """
    device_type = DeviceTypeSerializer(read_only=True)
    manufacturer = ManufacturerSerializer(read_only=True)
    device_group = DeviceGroupSerializer(read_only=True)
    user_permissions = serializers.SerializerMethodField()
    backup_method_display = serializers.SerializerMethodField()
    
    class Meta:
        model = Device
        fields = [
            'id', 'name', 'ip_address', 'dns_name', 'device_type', 'manufacturer',
            'backup_method', 'backup_method_display',
            'device_group', 'enabled', 'is_example_data', 'last_backup_time',
            'last_backup_status', 'retention_policy', 'backup_location', 'credential',
            'user_permissions'
        ]
    
    def get_user_permissions(self, obj):
        """Get permissions for the requesting user for this device's group"""
        from devices.permissions import user_get_device_group_permissions
        
        request = self.context.get('request')
        if not request or not request.user:
            return []
        
        if not obj.device_group:
            return []
        
        permissions = user_get_device_group_permissions(request.user, obj.device_group)
        return list(permissions)