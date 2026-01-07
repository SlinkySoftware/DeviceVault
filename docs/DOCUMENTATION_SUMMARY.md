# DeviceVault Code Documentation Summary

## Overview
This document summarizes the comprehensive documentation added to the DeviceVault application codebase. All major components now include detailed comments describing inputs, outputs, and functionality.

## Backend Documentation

### 1. Device Management (`backend/devices/models.py`)
- **DeviceType Model**: Network device categories with Material Design icons
  - Fields: name, icon
  - Purpose: Categorize devices (Router, Switch, Firewall, etc.)

- **Manufacturer Model**: Hardware device manufacturers
  - Fields: name
  - Purpose: Track device manufacturers

- **Device Model**: Network devices to be backed up
  - Fields: name, ip_address, dns_name, device_type, manufacturer, labels, enabled, is_example_data, last_backup_time, last_backup_status, retention_policy, backup_location, credential
  - Purpose: Core inventory management with full backup configuration

### 2. Backup Policies (`backend/policies/models.py`)
- **RetentionPolicy Model**: Backup cleanup and retention rules
  - Fields: name, max_backups, max_days, max_size_bytes
  - Purpose: Define how long to keep backups and cleanup triggers

- **BackupSchedule Model**: Automated backup scheduling via Celery Beat
  - Fields: name, description, schedule_type (daily/weekly/monthly/custom_cron), hour, minute, day_of_week, day_of_month, cron_expression, enabled, created_at, updated_at
  - Methods: get_celery_schedule() - generates Celery Beat configuration
  - Purpose: Define when backups execute automatically

### 3. Credentials (`backend/credentials/models.py`)
- **CredentialType Model**: Types of credential sources
  - Fields: name
  - Purpose: Local, CyberArk, HashiCorp Vault, Azure Key Vault, etc.

- **Credential Model**: Device access credentials
  - Fields: name, credential_type, data (JSON)
  - Purpose: Store authentication details for device connection

### 4. Backup Locations (`backend/locations/models.py`)
- **BackupLocation Model**: Where backups are stored
  - Fields: name, location_type, config (JSON)
  - Location types: git, s3, filesystem, tftp
  - Purpose: Specify backup storage destinations

### 5. Backup Records (`backend/backups/models.py`)
- **Backup Model**: Individual backup operation records
  - Fields: device, location, timestamp, status, size_bytes, artifact_path, is_text
  - Purpose: Track all backup operations and enable restore functionality

### 6. Core/User Management (`backend/core/models.py`)
- **Label Model**: Device organization tags
  - Fields: name, description
  - Purpose: Categorize devices (Production, DMZ, Critical, etc.)

- **UserProfile Model**: User preferences
  - Fields: user, theme (light/dark), created_at, updated_at
  - Purpose: Store UI preferences per user

- **DashboardLayout Model**: Dashboard widget configuration
  - Fields: user, is_default, layout (JSON array), created_at, updated_at
  - Purpose: Allow users to customize dashboard

### 7. Audit Logging (`backend/audit/models.py`)
- **AuditLog Model**: Tracks all user actions
  - Fields: created_at, actor, action, resource, details (JSON), label_scope
  - Purpose: Compliance, security auditing, debugging

### 8. Role-Based Access Control (`backend/rbac/models.py`)
- **Permission Model**: Granular action permissions
  - Fields: code, description
  - Examples: view_devices, edit_devices, manage_credentials, admin_access

- **Role Model**: Groups permissions and label scopes
  - Fields: name, permissions (M2M), labels (M2M)
  - Examples: Administrator, Operator, Viewer

- **UserRole Model**: Associates users with roles
  - Fields: user, role
  - Purpose: Assign roles to users for access control

### 9. API Serializers (`backend/api/serializers.py`)
- **Model Serializers**: Standard CRUD serializers for all models
  - DeviceTypeSerializer, ManufacturerSerializer, DeviceSerializer (with nested objects)
  - BackupScheduleSerializer, RetentionPolicySerializer, BackupLocationSerializer, etc.
  - Purpose: Convert models to/from JSON

- **Authentication Serializers**:
  - `LoginSerializer`: Validates username/password, returns authenticated user
  - `UserUpdateSerializer`: Editable user profile fields (email, name)
  - `ChangePasswordSerializer`: Password change with validation for local users only

### 10. API Views (Backend API Endpoints)
- Standard ViewSets for CRUD operations on all models
- Custom endpoints:
  - `onboarding`: Check if system is configured
  - `dashboard_stats`: Compute dashboard statistics
  - `LoginView`: Handle user authentication
  - `LogoutView`: Clear authentication token
  - `UserInfoView`: Get/update current user info
  - `ChangePasswordView`: Change password with validation

## Frontend Documentation

### 1. Services (`frontend/src/services/`)

#### API Service (`api.js`)
- **Purpose**: Centralized HTTP client for all API requests
- **Features**:
  - Automatic token injection from localStorage
  - Automatic 401 redirect to login
  - Consistent error handling
- **Request Interceptor**: Adds authentication token to all requests
- **Response Interceptor**: Handles session expiration

#### Configuration (`config.js`)
- **Purpose**: Centralized configuration management
- **Properties**: apiUrl, appName, version
- **Environment Variables**: VITE_API_URL or VUE_APP_API_URL

### 2. Application Setup (`main.js`)
- **Purpose**: Vue 3 application initialization
- **Setup**: Quasar framework, Vue Router, Material Icons
- **Mount Point**: #q-app element in index.html

### 3. Router (`router/index.js`)
- **Purpose**: Client-side routing and authentication guard
- **Route Groups**:
  - Public: /login (requiresAuth: false)
  - Main: / (Dashboard), /devices, /profile
  - Admin: /vaultadmin/* (Device Types, Manufacturers, Credentials, etc.)
- **Authentication Guard**: Protects routes requiring login
  - Redirects unauthenticated users to /login
  - Redirects authenticated users away from /login to dashboard

### 4. Pages (Vue Components)

#### Devices Page (`pages/Devices.vue`)
- **Purpose**: List and manage all network devices
- **Features**:
  - Tabular display with sorting
  - Filter by manufacturer, type, backup status
  - Edit device details
  - View backup history
  - Enable/disable for backups
  - Icon display for device types
  - Example data badge
- **Key Functions**:
  - `loadDevices()`: Fetch all devices from API
  - `toggleEnabled(device)`: Enable/disable device for backups
- **Computed Properties**:
  - `filteredDevices`: Applies all active filters

#### Backup Schedules Page (`pages/BackupSchedules.vue`)
- **Purpose**: Manage automated backup schedules (Celery Beat)
- **Features**:
  - Create daily, weekly, monthly, custom cron schedules
  - Set schedule times (hour, minute, day)
  - Enable/disable schedules
  - Full CRUD operations
  - Human-readable schedule display
- **Key Functions**:
  - `loadData()`: Load all schedules from API
  - `showAddDialog()`: Open add schedule dialog
  - `editItem(item)`: Open edit dialog for schedule
  - `save()`: Create or update schedule
  - `deleteItem(item)`: Delete schedule with confirmation
  - `getDayName(dayNum)`: Convert day number to name
- **Form Fields**: name, description, schedule_type, hour, minute, day_of_week, day_of_month, cron_expression, enabled

## Documentation Standards Applied

### Python Backend Files
- **Module-level docstring**: Purpose and functionality overview
- **Class docstrings**: Model description, fields, methods, usage
- **Field help_text**: Every model field documented
- **Method docstrings**: Parameters, returns, behavior
- **Inline comments**: Complex logic and edge cases

### JavaScript/Vue Files
- **JSDoc comments**: Function signatures with parameters and returns
- **Block comments**: Section headers for logical grouping
- **Inline comments**: Complex logic and important notes
- **Component comments**: Purpose, features, and responsibility

## Files Documented

### Backend Models (10 files)
- ✅ devices/models.py (DeviceType, Manufacturer, Device)
- ✅ policies/models.py (RetentionPolicy, BackupSchedule)
- ✅ credentials/models.py (CredentialType, Credential)
- ✅ locations/models.py (BackupLocation)
- ✅ backups/models.py (Backup)
- ✅ core/models.py (Label, UserProfile, DashboardLayout)
- ✅ audit/models.py (AuditLog)
- ✅ rbac/models.py (Permission, Role, UserRole)
- ✅ api/serializers.py (All serializers with detailed comments)
- ✅ api/views.py (ViewSets and API endpoints)

### Frontend Services (2 files)
- ✅ src/services/api.js (HTTP client with interceptors)
- ✅ src/services/config.js (Configuration management)

### Frontend Setup (2 files)
- ✅ src/main.js (Vue 3 initialization)
- ✅ src/router/index.js (Client-side routing)

### Frontend Pages (2 major files documented)
- ✅ src/pages/Devices.vue (Device management page)
- ✅ src/pages/BackupSchedules.vue (Schedule management page)

## Key Documentation Patterns

### Model Fields Documentation
```python
field_name = models.FieldType(
    help_text='Description of what this field stores and how it\'s used'
)
```

### Function Documentation
```python
def function_name(param1, param2):
    """
    Brief description of what function does
    
    Args:
        param1 (type): Description
        param2 (type): Description
    
    Returns:
        return_type: Description of return value
    
    Raises:
        ExceptionType: When this exception occurs
    """
```

### Vue Component Documentation
```javascript
/**
 * Component Name and Purpose
 * 
 * Features:
 * - Feature 1
 * - Feature 2
 * 
 * Component State:
 * - state1: Description
 * - state2: Description
 * 
 * Methods:
 * - method1(): Description
 */
```

## Maintenance Notes

- All docstrings follow consistent formatting
- Complex logic includes inline explanations
- Field help_text provides context for admins
- API documentation aids frontend developers
- Router documentation clarifies navigation flow
- Service documentation explains data flow

## Next Steps

The following files could benefit from additional documentation:
- Other frontend pages (Users, Credentials, RetentionPolicies, etc.)
- Backend API permissions.py
- Backend storage connectors (fs.py, git.py)
- TFTP server implementation
- Management commands (create_admin.py)
- Celery task definitions (if present)

