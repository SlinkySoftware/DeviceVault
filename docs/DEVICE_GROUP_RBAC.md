# Device Group RBAC Implementation

## Overview
This implementation replaces the local labels/tags system with a comprehensive Django Role-Based Access Control (RBAC) system centered around Device Groups.

## Key Changes

### 1. Models
- **DeviceGroup**: Organizes devices into logical groups for RBAC control
- **DeviceGroupPermission**: Defines 6 granular permissions for device operations
- **DeviceGroupRole**: Bundles permissions for a specific device group
- **UserDeviceGroupRole**: Assigns device group roles directly to users
- **GroupDeviceGroupRole**: Assigns device group roles to Django auth groups
- **Device.device_group**: Each device now belongs to exactly one device group (nullable for migration)

### 2. Permissions
Six granular permissions control device operations:
- `view_configuration`: View device configuration backups
- `view_backups`: View and download backup history
- `edit_configuration`: Modify device configuration
- `add_device`: Add new devices to the group
- `delete_device`: Delete devices from the group
- `enable_device`: Enable/disable devices in the group

### 3. Permission Checking Utilities
Location: `backend/rbac/permissions.py`

#### Functions:
- `user_has_device_group_permission(user, device_group, permission_code)`: Check single permission
- `user_get_device_group_permissions(user, device_group)`: Get all permissions for user in group
- `user_get_accessible_device_groups(user)`: Get all groups user has access to

#### REST Framework Permission Classes:
- `CanViewDeviceConfiguration`: Object-level permission for viewing configs
- `CanViewBackups`: Object-level permission for viewing backups
- `CanEditConfiguration`: Object-level permission for editing configs
- `CanAddDevice`: View-level permission to add devices
- `CanDeleteDevice`: Object-level permission to delete devices
- `CanEnableDevice`: Object-level permission to enable/disable devices

### 4. API Endpoints

#### Device Groups Management
- `GET/POST /api/device-groups/` - List/create device groups
- `GET/PATCH/DELETE /api/device-groups/{id}/` - Manage specific group

#### Device Group Roles
- `GET/POST /api/device-group-roles/` - List/create roles
- `GET/PATCH/DELETE /api/device-group-roles/{id}/` - Manage specific role

#### Permissions (Read-Only)
- `GET /api/device-group-permissions/` - List available permissions

#### Role Assignments
- `GET/POST /api/user-device-group-roles/` - Assign/list user roles
- `GET/POST /api/group-device-group-roles/` - Assign/list auth group roles

#### Devices
- Enhanced to return `user_permissions` field in detail response
- Filtered automatically based on user's accessible device groups
- Respects permission checks for delete operations

### 5. Serializers
Location: `backend/api/serializers.py`

New serializers:
- `DeviceGroupSerializer`: Device group with nested roles
- `DeviceGroupRoleSerializer`: Role with nested permissions
- `DeviceGroupPermissionSerializer`: Permission details
- `UserDeviceGroupRoleSerializer`: User role assignment
- `GroupDeviceGroupRoleSerializer`: Auth group role assignment
- `DeviceDetailedSerializer`: Enhanced device serializer with user permissions

### 6. Migrations
Created automatic migrations for:
- `rbac.0005_devicegroup_devicegrouppermission_devicegrouprole_and_more.py`
- `devices.0004_device_device_group_alter_device_backup_location_and_more.py`

### 7. Management Command
- `python manage.py init_device_group_permissions`: Initialize 6 default permissions

## Usage Examples

### Creating a Device Group
```python
from rbac.models import DeviceGroup, DeviceGroupRole, DeviceGroupPermission

group = DeviceGroup.objects.create(
    name="Production Routers",
    description="Production network routers"
)

# Get all available permissions
permissions = DeviceGroupPermission.objects.all()

# Create a role with specific permissions
role = group.roles.create(
    name="Operator",
    description="Can view and manage devices"
)
role.permissions.add(*permissions.filter(code__in=[
    'view_configuration',
    'view_backups',
    'edit_configuration',
    'enable_device'
]))
```

### Assigning Roles to Users
```python
from rbac.models import UserDeviceGroupRole
from django.contrib.auth.models import User

user = User.objects.get(username='operator')
role = DeviceGroupRole.objects.get(name='Operator', device_group=group)

UserDeviceGroupRole.objects.create(user=user, role=role)
```

### Checking Permissions
```python
from rbac.permissions import user_has_device_group_permission

user = User.objects.get(username='operator')
group = DeviceGroup.objects.get(name='Production Routers')

can_edit = user_has_device_group_permission(user, group, 'edit_configuration')
# Returns: True or False
```

### Getting User's Accessible Groups
```python
from rbac.permissions import user_get_accessible_device_groups

user = User.objects.get(username='operator')
groups = user_get_accessible_device_groups(user)
# Returns: QuerySet of DeviceGroup objects user has access to
```

## Frontend Integration

### Device List View
- Show "Add Device" button only if user has `add_device` permission in at least one group
- Show "Edit" action only if user has `edit_configuration` permission for device's group
- Show "View Backups" action only if user has `view_backups` permission for device's group
- Show "Delete" action only if user has `delete_device` permission for device's group

### Device Detail View
- Use `user_permissions` array returned from API to control visible actions
- Request includes permission check results

### Group Management Page
- List all accessible device groups (filtered by user's roles)
- Show device count per group
- Manage roles and user assignments
- Only admins can create/edit groups and roles

## Security Notes

1. **Staff/Superuser Bypass**: Staff users and superusers have all permissions
2. **Group Inheritance**: Users inherit permissions from both direct assignments AND auth group memberships
3. **Multiple Roles**: Users can have multiple roles across different device groups
4. **No Device Access Without Group**: Devices without a device group are hidden from non-admin users
5. **Filtered API Responses**: Devices are automatically filtered based on accessible groups

## Migration Path
1. Create device groups matching your organizational structure
2. Assign devices to appropriate groups (can be done via admin or API)
3. Create roles with appropriate permissions for each group
4. Assign users/groups to roles
5. Frontend automatically respects new permission model
6. Old labels remain for backward compatibility (can be migrated separately)

## Next Steps
1. Update frontend to consume `user_permissions` field
2. Hide UI elements based on permissions
3. Update Group Management page to show device group configuration
4. Create admin interface for device group management (if needed beyond API)
