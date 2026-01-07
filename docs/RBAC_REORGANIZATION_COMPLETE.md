# RBAC App Reorganization - Completion Summary

## Overview
Successfully moved DeviceGroup-related models and permissions from the monolithic `rbac` app to the `devices` app, improving code organization and separation of concerns.

## What Was Changed

### 1. Model Relocation
Moved the following models from `rbac/models.py` to `devices/models.py`:
- `DeviceGroup` - Base device group model
- `DeviceGroupPermission` - Permission definitions for device groups
- `DeviceGroupRole` - Role definitions per device group
- `UserDeviceGroupRole` - User-to-role assignments
- `GroupDeviceGroupRole` - Group-to-role assignments
- `DeviceGroupDjangoPermissions` - Django auth permission mappings
- Associated signals: `ensure_django_permissions_on_save`, `prevent_delete_if_permissions_in_use`

### 2. Import Updates
Updated imports across the codebase:
- **rbac/permissions.py**: Changed imports from `rbac.models` to `devices.models`
- **api/serializers.py**: Split imports between `rbac.models` (legacy) and `devices.models` (DeviceGroup)
- **api/views.py**: Updated DeviceGroupViewSet to import from `devices.models`

### 3. RBAC App Cleanup
- Backed up original file: `rbac/models.py.bak`
- Created minimal `rbac/models.py` containing only legacy models:
  - `Permission`
  - `Role`
  - `UserRole`
  - `GroupLabelAssignment`
- Each marked with deprecation notes

### 4. Database Migrations
Created and applied migrations:

#### devices/migrations/0006_move_devicegroup_from_rbac.py
- Uses `SeparateDatabaseAndState` to move models without recreating tables
- Updates Django's state to show models belong to devices app
- Preserves existing database tables with `db_table` settings

#### rbac/migrations/0008_remove_devicegroup_models.py
- Uses `SeparateDatabaseAndState` to remove models from rbac app state
- No database changes (tables now managed by devices app)

### 5. Permission Migration
Created `migrate_permissions_raw.py` to update Django's auth permissions:
- Migrated ContentType references from `rbac.*` to `devices.*` for 6 models
- Updated all user and group permission assignments
- Updated `rbac_devicegroupdjangopermissions` table FK references
- Preserved custom DeviceGroup permissions (e.g., `rbac_dg_it_networks_switches_add`)

## Verification Results

### System Check
```bash
python manage.py check
# System check identified no issues (0 silenced).
```

### ContentType Organization
**RBAC App** (legacy only):
- rbac.devicegroupdjangoroles (4 permissions)
- rbac.group (4 permissions)
- rbac.grouplabelassignment (4 permissions)
- rbac.permission (4 permissions)
- rbac.role (4 permissions)
- rbac.userrole (4 permissions)

**Devices App** (includes DeviceGroup RBAC):
- devices.device (4 permissions)
- devices.devicegroup (8 permissions) ✓
- devices.devicegroupdjangopermissions (4 permissions) ✓
- devices.devicegrouppermission (4 permissions) ✓
- devices.devicegrouprole (4 permissions) ✓
- devices.devicetype (4 permissions)
- devices.groupdevicegrouprole (4 permissions) ✓
- devices.manufacturer (4 permissions)
- devices.userdevicegrouprole (4 permissions) ✓

### Custom Permissions Preserved
All custom DeviceGroup permissions successfully migrated:
- `rbac_dg_it_networks_switches_add`
- `rbac_dg_it_networks_switches_change`
- `rbac_dg_it_networks_switches_delete`
- `rbac_dg_it_networks_switches_view`

## Database Schema
No table names or structure changed:
- Tables remain prefixed with `rbac_` (e.g., `rbac_devicegroup`)
- Django now recognizes these as belonging to `devices` app
- All foreign keys and relationships intact

## Files Created/Modified

### New Files
- `backend/migrate_devicegroup_to_devices.py` - Initial Django ORM migration script
- `backend/migrate_permissions_raw.py` - Raw SQL permission migration script
- `backend/list_rbac_permissions.py` - Permission listing utility
- `backend/devices/migrations/0006_move_devicegroup_from_rbac.py`
- `backend/rbac/migrations/0008_remove_devicegroup_models.py`

### Modified Files
- `backend/devices/models.py` - Added all DeviceGroup models (~250 lines)
- `backend/rbac/models.py` - Reduced to 69 lines (legacy models only)
- `backend/rbac/permissions.py` - Updated imports
- `backend/api/serializers.py` - Split imports
- `backend/api/views.py` - Updated imports

### Backup Files
- `backend/rbac/models.py.bak` - Original rbac/models.py preserved

## Next Steps (Optional)

### 1. Legacy Model Cleanup
Analyze usage of legacy models and consider removal:
- `rbac.Permission` - Check if still in use
- `rbac.Role` - Check if still in use  
- `rbac.UserRole` - Check if still in use
- `rbac.GroupLabelAssignment` - Check if still in use
- `rbac.devicegroupdjangoroles` - Old table, likely obsolete

### 2. Table Renaming (Optional)
Consider renaming tables from `rbac_*` to `devices_*`:
- Would require data migration
- Impact on existing installations
- Only needed for clean separation

### 3. Documentation Updates
Update any documentation referencing:
- `from rbac.models import DeviceGroup` → `from devices.models import DeviceGroup`
- RBAC app structure and organization
- Permission management workflows

## Impact Assessment
✅ **No Breaking Changes**:
- All functionality preserved
- Database schema unchanged
- API endpoints unchanged
- Permission checking unchanged

✅ **Benefits**:
- Cleaner code organization
- Domain-specific model grouping
- Easier to understand codebase
- RBAC app reduced to minimal legacy code

## Rollback Plan
If needed, restore from backup:
```bash
mv backend/rbac/models.py.bak backend/rbac/models.py
python manage.py migrate rbac 0007_devicegroupdjangopermissions_and_more
python manage.py migrate devices 0005_remove_device_labels
# Re-run reverse permission migration
```
