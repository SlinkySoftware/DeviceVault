"""
Device Group RBAC Permission Checking Utilities
Provides functions to check if a user has specific permissions for a device group.
"""

from devices.models import (
    UserDeviceGroupRole, GroupDeviceGroupRole, 
    DeviceGroupRole, DeviceGroupPermission
)
from django.contrib.auth.models import User
from rest_framework.permissions import BasePermission


def user_has_device_group_permission(user: User, device_group, permission_code: str) -> bool:
    """
    Check if a user has a specific permission for a device group.
    
    Args:
        user: Django User instance
        device_group: DeviceGroup instance
        permission_code: Permission code (e.g., 'view_configuration', 'edit_configuration')
    
    Returns:
        bool: True if user has permission, False otherwise
    
    Permission Codes:
        - view_configuration: Can view device configuration backups
        - view_backups: Can view/download backup history
        - edit_configuration: Can modify device configuration
        - add_device: Can add devices to the group
        - delete_device: Can delete devices from the group
        - enable_device: Can enable/disable devices in the group
    """
    if user.is_staff or user.is_superuser:
        return True
    
    # Check direct user assignments
    user_roles = UserDeviceGroupRole.objects.filter(
        user=user,
        role__device_group=device_group
    ).values_list('role_id', flat=True)
    
    # Check group assignments (user is member of an auth group with device group role)
    group_roles = GroupDeviceGroupRole.objects.filter(
        auth_group__user=user,
        role__device_group=device_group
    ).values_list('role_id', flat=True)
    
    all_roles = list(user_roles) + list(group_roles)
    
    if not all_roles:
        return False
    
    # Check if any of the user's roles have the permission
    has_permission = DeviceGroupRole.objects.filter(
        id__in=all_roles,
        permissions__code=permission_code
    ).exists()
    
    return has_permission


def user_get_device_group_permissions(user: User, device_group) -> set:
    """
    Get all permissions a user has for a device group.
    
    Args:
        user: Django User instance
        device_group: DeviceGroup instance
    
    Returns:
        set: Set of permission codes the user has for this device group
    """
    if user.is_staff or user.is_superuser:
        return set(DeviceGroupPermission.objects.values_list('code', flat=True))
    
    # Check direct user assignments
    user_roles = UserDeviceGroupRole.objects.filter(
        user=user,
        role__device_group=device_group
    ).values_list('role_id', flat=True)
    
    # Check group assignments
    group_roles = GroupDeviceGroupRole.objects.filter(
        auth_group__user=user,
        role__device_group=device_group
    ).values_list('role_id', flat=True)
    
    all_roles = list(user_roles) + list(group_roles)
    
    if not all_roles:
        return set()
    
    # Get all permissions from user's roles
    permissions = DeviceGroupRole.objects.filter(
        id__in=all_roles
    ).prefetch_related('permissions').values_list(
        'permissions__code', flat=True
    ).distinct()
    
    return set(permissions)


def user_get_accessible_device_groups(user: User):
    """
    Get all device groups a user has at least some access to.
    
    Args:
        user: Django User instance
    
    Returns:
        QuerySet: DeviceGroup instances user has access to
    """
    from devices.models import DeviceGroup
    
    if user.is_staff or user.is_superuser:
        return DeviceGroup.objects.all()
    
    # Get device groups from direct user role assignments
    user_device_groups = DeviceGroup.objects.filter(
        roles__userdevicegrouprole__user=user
    )
    
    # Get device groups from auth group role assignments
    group_device_groups = DeviceGroup.objects.filter(
        roles__groupdevicegrouprole__auth_group__user=user
    )
    
    return (user_device_groups | group_device_groups).distinct()

# ===== REST Framework Permission Classes =====

class CanViewDeviceConfiguration(BasePermission):
    """Permission to view device configuration backups"""
    
    def has_object_permission(self, request, view, obj):
        """Check if user can view configuration for this device's group"""
        if request.user.is_staff or request.user.is_superuser:
            return True
        
        if not obj.device_group:
            return False
        
        return user_has_device_group_permission(request.user, obj.device_group, 'view_configuration')


class CanViewBackups(BasePermission):
    """Permission to view backup history"""
    
    def has_object_permission(self, request, view, obj):
        """Check if user can view backups for this device's group"""
        if request.user.is_staff or request.user.is_superuser:
            return True
        
        if not obj.device_group:
            return False
        
        return user_has_device_group_permission(request.user, obj.device_group, 'view_backups')


class CanEditConfiguration(BasePermission):
    """Permission to edit device configuration"""
    
    def has_object_permission(self, request, view, obj):
        """Check if user can edit configuration for this device's group"""
        if request.user.is_staff or request.user.is_superuser:
            return True
        
        if not obj.device_group:
            return False
        
        return user_has_device_group_permission(request.user, obj.device_group, 'edit_configuration')


class CanAddDevice(BasePermission):
    """Permission to add devices to a device group"""
    
    def has_permission(self, request, view):
        """Check if user can add devices to any group"""
        if request.user.is_staff or request.user.is_superuser:
            return True
        
        # Check if user has 'add_device' permission for at least one device group
        accessible_groups = user_get_accessible_device_groups(request.user)
        
        for group in accessible_groups:
            if user_has_device_group_permission(request.user, group, 'add_device'):
                return True
        
        return False


class CanDeleteDevice(BasePermission):
    """Permission to delete devices from a device group"""
    
    def has_object_permission(self, request, view, obj):
        """Check if user can delete device from its group"""
        if request.user.is_staff or request.user.is_superuser:
            return True
        
        if not obj.device_group:
            return False
        
        return user_has_device_group_permission(request.user, obj.device_group, 'delete_device')


class CanEnableDevice(BasePermission):
    """Permission to enable/disable devices in a device group"""
    
    def has_object_permission(self, request, view, obj):
        """Check if user can enable/disable device in its group"""
        if request.user.is_staff or request.user.is_superuser:
            return True
        
        if not obj.device_group:
            return False
        
        return user_has_device_group_permission(request.user, obj.device_group, 'enable_device')