"""
Device Group RBAC Permission Checking Utilities
Moved from rbac.permissions; uses devices models directly.
"""

from devices.models import (
    UserDeviceGroupRole,
    GroupDeviceGroupRole,
    DeviceGroupRole,
    DeviceGroupPermission,
    DeviceGroup,
)
from django.contrib.auth.models import User
from rest_framework.permissions import BasePermission


def user_has_device_group_permission(user: User, device_group, permission_code: str) -> bool:
    """Check if a user has a specific permission for a device group."""
    if user.is_staff or user.is_superuser:
        return True
    user_roles = UserDeviceGroupRole.objects.filter(
        user=user,
        role__device_group=device_group,
    ).values_list('role_id', flat=True)
    group_roles = GroupDeviceGroupRole.objects.filter(
        auth_group__user=user,
        role__device_group=device_group,
    ).values_list('role_id', flat=True)
    all_roles = list(user_roles) + list(group_roles)
    if not all_roles:
        return False
    return DeviceGroupRole.objects.filter(
        id__in=all_roles,
        permissions__code=permission_code,
    ).exists()


def user_get_device_group_permissions(user: User, device_group) -> set:
    """Return permission codes a user has for a device group."""
    if user.is_staff or user.is_superuser:
        return set(DeviceGroupPermission.objects.values_list('code', flat=True))
    user_roles = UserDeviceGroupRole.objects.filter(
        user=user,
        role__device_group=device_group,
    ).values_list('role_id', flat=True)
    group_roles = GroupDeviceGroupRole.objects.filter(
        auth_group__user=user,
        role__device_group=device_group,
    ).values_list('role_id', flat=True)
    all_roles = list(user_roles) + list(group_roles)
    if not all_roles:
        return set()
    permissions = DeviceGroupRole.objects.filter(
        id__in=all_roles,
    ).prefetch_related('permissions').values_list(
        'permissions__code', flat=True,
    ).distinct()
    return set(permissions)


def user_get_accessible_device_groups(user: User):
    """Return device groups a user has at least some access to."""
    if user.is_staff or user.is_superuser:
        return DeviceGroup.objects.all()
    user_device_groups = DeviceGroup.objects.filter(
        roles__userdevicegrouprole__user=user,
    )
    group_device_groups = DeviceGroup.objects.filter(
        roles__groupdevicegrouprole__auth_group__user=user,
    )
    return (user_device_groups | group_device_groups).distinct()


# ===== REST Framework Permission Classes =====

class CanViewDeviceConfiguration(BasePermission):
    def has_object_permission(self, request, view, obj):
        if request.user.is_staff or request.user.is_superuser:
            return True
        if not obj.device_group:
            return False
        return user_has_device_group_permission(request.user, obj.device_group, 'view_configuration')


class CanViewBackups(BasePermission):
    def has_object_permission(self, request, view, obj):
        if request.user.is_staff or request.user.is_superuser:
            return True
        if not obj.device_group:
            return False
        return user_has_device_group_permission(request.user, obj.device_group, 'view_backups')


class CanEditConfiguration(BasePermission):
    def has_object_permission(self, request, view, obj):
        if request.user.is_staff or request.user.is_superuser:
            return True
        if not obj.device_group:
            return False
        return user_has_device_group_permission(request.user, obj.device_group, 'edit_configuration')


class CanAddDevice(BasePermission):
    def has_permission(self, request, view):
        if request.user.is_staff or request.user.is_superuser:
            return True
        accessible_groups = user_get_accessible_device_groups(request.user)
        for group in accessible_groups:
            if user_has_device_group_permission(request.user, group, 'add_device'):
                return True
        return False


class CanDeleteDevice(BasePermission):
    def has_object_permission(self, request, view, obj):
        if request.user.is_staff or request.user.is_superuser:
            return True
        if not obj.device_group:
            return False
        return user_has_device_group_permission(request.user, obj.device_group, 'delete_device')


class CanEnableDevice(BasePermission):
    def has_object_permission(self, request, view, obj):
        if request.user.is_staff or request.user.is_superuser:
            return True
        if not obj.device_group:
            return False
        return user_has_device_group_permission(request.user, obj.device_group, 'enable_device')
