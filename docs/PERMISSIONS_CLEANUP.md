# Django Permissions Cleanup

## Overview
Removed unused legacy RBAC models and permissions from the system after the DeviceGroup RBAC reorganization. The rbac app is now minimal, containing only GroupLabelAssignment.

## What Was Removed

### 1. Legacy Models (rbac app)
- **Permission** - Legacy permission model (replaced by DeviceGroupPermission in devices app)
- **Role** - Legacy role model (replaced by DeviceGroupRole in devices app)
- **UserRole** - Legacy user-role assignments (replaced by UserDeviceGroupRole in devices app)

**Rationale**: These models were marked as "legacy infrastructure" and were only used by seed_data.py. The new DeviceGroup RBAC system (in devices app) provides superior functionality with per-group permissions.

### 2. API Endpoints
- **DELETE /api/roles/** - RoleViewSet removed
- **DELETE /api/permissions/** - PermissionViewSet removed

**Rationale**: These endpoints were registered but never used by the frontend. All RBAC is now handled through device group roles (/api/device-group-roles/).

### 3. Database Tables
Removed via migration:
- `rbac_permission`
- `rbac_role`
- `rbac_role_permissions` (M2M table)
- `rbac_role_labels` (M2M table)
- `rbac_userrole`

### 4. Django ContentTypes & Permissions
Cleaned up 20 obsolete permissions across 5 ContentTypes:
- rbac.permission (4 permissions)
- rbac.role (4 permissions)
- rbac.userrole (4 permissions)
- rbac.devicegroupdjangoroles (4 permissions - obsolete)
- rbac.group (4 permissions - never had a model)

### 5. Management Command
- **DELETE** `rbac/management/commands/init_device_group_permissions.py`

**Rationale**: This command referenced `rbac.models.DeviceGroupPermission` which was moved to `devices.models.DeviceGroupPermission`. DeviceGroup permissions are now auto-created via signals.

### 6. Seed Data Updates
Removed permission and role seeding from seed_data.py:
- Removed imports: `Permission, Role` from rbac.models
- Removed permission creation code (6 permissions)
- Removed role creation code (Administrator, Operator roles)

**Rationale**: These legacy models no longer exist. DeviceGroup permissions are the new standard.

## What Remains

### rbac App (Minimal)
**Single Model**: `GroupLabelAssignment`
- Purpose: Maps Django auth Groups to Labels for tag-based device filtering
- Status: Active, used by GroupViewSet
- Permissions: 4 (add, change, delete, view)

### Database Tables (rbac_*)
While Django's model state is clean, some database tables remain with `rbac_` prefix:
- `rbac_grouplabelassignment` - Active (for GroupLabelAssignment model)
- `rbac_devicegroup` - Active (managed by devices app, keeps prefix for backward compatibility)
- `rbac_devicegrouppermission` - Active (managed by devices app)
- `rbac_devicegrouprole` - Active (managed by devices app)
- `rbac_devicegroupdjangopermissions` - Active (managed by devices app)
- `rbac_userdevicegrouprole` - Active (managed by devices app)
- `rbac_groupdevicegrouprole` - Active (managed by devices app)

**Note**: These tables use `db_table='rbac_...'` in their model Meta to maintain backward compatibility after migration from rbac to devices app.

### devices App (DeviceGroup RBAC)
**Active Models** (all use rbac_ table prefix):
- DeviceGroup
- DeviceGroupPermission
- DeviceGroupRole
- UserDeviceGroupRole
- GroupDeviceGroupRole
- DeviceGroupDjangoPermissions

**API Endpoints**:
- /api/device-groups/
- /api/device-group-roles/
- /api/device-group-permissions/
- /api/user-device-group-roles/
- /api/group-device-group-roles/

## Files Modified

### Backend
1. **rbac/models.py** - Removed Permission, Role, UserRole models
2. **api/serializers.py** - Removed PermissionSerializer, RoleSerializer
3. **api/views.py** - Removed RoleViewSet, PermissionViewSet
4. **devicevault/urls.py** - Removed /api/roles/ and /api/permissions/ routes
5. **seed_data.py** - Removed permission and role seeding code
6. **rbac/migrations/0009_remove_legacy_models.py** - New migration to drop tables

### Deleted Files
- `rbac/management/commands/init_device_group_permissions.py`

## Migration Details

### Migration: rbac.0009_remove_legacy_models
**Type**: RunPython with raw SQL

**Operations**:
```python
DROP TABLE IF EXISTS rbac_userrole
DROP TABLE IF EXISTS rbac_role_permissions
DROP TABLE IF EXISTS rbac_role_labels
DROP TABLE IF EXISTS rbac_role
DROP TABLE IF EXISTS rbac_permission
```

**Applied**: Yes ✓

### ContentType Cleanup Script
Executed manual cleanup to remove obsolete Django ContentTypes and Permissions:
```python
# Removed ContentTypes for deleted models
ContentType.objects.filter(app_label='rbac', model__in=[
    'permission', 'role', 'userrole', 'devicegroupdjangoroles', 'group'
]).delete()
```

## Verification

### System Check
```bash
python manage.py check
# System check identified no issues (0 silenced).
```

### ContentType Verification
- **rbac app**: 1 ContentType (grouplabelassignment)
- **devices app**: 6 DeviceGroup ContentTypes with 28 permissions

### API Endpoint Check
```bash
# Removed (return 404):
GET /api/roles/ → 404
GET /api/permissions/ → 404

# Active:
GET /api/device-group-roles/ → 200 OK
GET /api/device-group-permissions/ → 200 OK
```

## Impact Assessment

### ✅ Zero Breaking Changes
- No frontend code used /api/roles/ or /api/permissions/ endpoints
- seed_data.py permissions/roles were demo data only
- DeviceGroup RBAC (new system) unaffected
- All admin permissions still work via Django's auth system

### ✅ Database Space Saved
- 5 tables dropped
- 20 unused permissions removed
- Cleaner ContentType registry

### ✅ Code Clarity
- Removed deprecated "legacy" models
- Single source of truth: DeviceGroup RBAC in devices app
- Simpler rbac app (1 model vs 4 models)

### ✅ Maintenance Improved
- Fewer models to maintain
- No confusion about which RBAC system to use
- Clear separation: GroupLabelAssignment (tag-based) vs DeviceGroup RBAC (permission-based)

## Rollback Plan

If rollback needed:
1. Revert rbac/models.py to restore Permission, Role, UserRole
2. Revert api/serializers.py to restore serializers
3. Revert api/views.py to restore viewsets
4. Revert devicevault/urls.py to restore routes
5. Revert seed_data.py to restore demo data
6. Run: `python manage.py migrate rbac 0008_remove_devicegroup_models`

**Backup**: Original models saved in `rbac/models.py.bak`

## Future Considerations

### Potential Additional Cleanup
1. **Table Renaming**: Rename `rbac_devicegroup*` tables to `devices_devicegroup*`
   - Requires data migration
   - Would complete the app separation
   - Not urgent - current setup works fine

2. **GroupLabelAssignment Evaluation**:
   - Assess if tag-based filtering is still needed
   - Consider merging into devices app if used primarily for devices
   - Keep in rbac if used across multiple apps

3. **Remove rbac app entirely**:
   - Only if GroupLabelAssignment is no longer needed
   - Would require moving or removing the model

## Related Documentation
- [RBAC_REORGANIZATION_COMPLETE.md](RBAC_REORGANIZATION_COMPLETE.md) - Original DeviceGroup migration
- [USER_MANAGEMENT_FIX.md](USER_MANAGEMENT_FIX.md) - User management updates

## Summary Statistics

**Before Cleanup**:
- RBAC models: 7 (4 legacy + 3 active)
- API endpoints: 2 unused (/api/roles/, /api/permissions/)
- ContentTypes: 6 in rbac app
- Django permissions: 24 in rbac app

**After Cleanup**:
- RBAC models: 1 (GroupLabelAssignment only)
- API endpoints: 0 unused
- ContentTypes: 1 in rbac app
- Django permissions: 4 in rbac app (for GroupLabelAssignment)

**Net Result**: Removed 6 models, 2 endpoints, 5 ContentTypes, 20 permissions
