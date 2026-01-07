# User Management Fix - Add User Button

## Issue
Admin users could not see an "Add User" button on the user management page because:
1. UserViewSet was ReadOnlyModelViewSet (no create/update/delete support)
2. Frontend had no "Add User" button
3. No check for local auth configuration
4. No user creation form

## Root Cause
According to original requirements: "No creation of local accounts (other than the initial local admin account) should be possible unless local auth is configured."

The system was correctly preventing user creation, but not communicating this to the user through the UI.

## Changes Made

### Backend Changes

#### 1. api/views.py - UserViewSet
**Changed from:** `ReadOnlyModelViewSet` → `ModelViewSet`

**Added Methods:**
- `_is_local_auth_enabled()`: Checks config.yaml for local auth
- `create()`: Create users only when local auth enabled (staff only)
- `update()`: Update users (staff only, not JIT users)
- `destroy()`: Delete users (staff only, prevents deleting last superuser)

**Permission Logic:**
- Only `is_staff` users can create/update/delete users
- User creation blocked if local auth is disabled with clear error message
- JIT-provisioned users cannot be edited (managed by external IdP)
- Last superuser cannot be deleted

#### 2. api/views.py - AuthConfigView
**Enhanced** to return auth configuration:
```python
{
  'providers': ['LDAP','SAML','EntraID','Local'],
  'local_enabled': true/false,  # NEW
  'auth_type': 'Local'/None     # NEW
}
```

#### 3. api/serializers.py - UserSerializer
**Added:**
- `password` field (write_only) for user creation
- `create()` method to properly hash passwords

### Frontend Changes

#### 1. pages/Users.vue - Template
**Added:**
- Conditional "Add User" button (shown only when `localAuthEnabled`)
- Disabled button with tooltip when local auth is disabled
- Warning message in subtitle when local auth is disabled
- Complete "Add User" dialog with form fields:
  - Username (required)
  - Email
  - First Name
  - Last Name
  - Password (required)
  - Confirm Password (required, must match)

**UI States:**
- **Local auth enabled**: Green "Add User" button, no warning
- **Local auth disabled**: Grey disabled button with tooltip, orange warning message

#### 2. pages/Users.vue - Script
**Added Data:**
- `localAuthEnabled`: Boolean flag from auth config
- `addDialog`: Dialog state for adding users
- `addForm`: Form data for new user

**Added Methods:**
- `fetchAuthConfig()`: Loads auth config to check local auth status
- `showAddUserDialog()`: Opens the add user dialog
- `createUser()`: Creates new user via POST /users/

**Updated:**
- `mounted()`: Now calls `fetchAuthConfig()` on page load

### Configuration

#### backend/config/config.yaml
**Added** auth configuration section:
```yaml
auth:
  type: Local
  local_enabled: true
```

This enables local user creation.

## API Endpoints

### GET /api/auth/config/
**Response:**
```json
{
  "providers": ["LDAP", "SAML", "EntraID", "Local"],
  "local_enabled": true,
  "auth_type": "Local"
}
```

### POST /api/users/
**Request:**
```json
{
  "username": "newuser",
  "email": "user@example.com",
  "first_name": "John",
  "last_name": "Doe",
  "password": "securepassword"
}
```

**Responses:**
- **201 Created**: User created successfully
- **403 Forbidden**: Local auth not enabled OR not staff user
- **400 Bad Request**: Validation errors

### PATCH /PUT /api/users/{id}/
Update user details (staff only, not JIT users)

### DELETE /api/users/{id}/
Delete user (staff only, prevents deleting last superuser)

## Permission Matrix

| Action | Staff | Non-Staff | Local Auth Required | JIT Users Editable |
|--------|-------|-----------|---------------------|-------------------|
| View Users | ✅ | ✅ | ❌ | N/A |
| Create User | ✅ | ❌ | ✅ | N/A |
| Update User | ✅ | ❌ | ❌ | ❌ |
| Delete User | ✅ | ❌ | ❌ | N/A |
| Update Own Profile | ✅ | ✅ | ❌ | ❌ (if JIT) |

## Testing

### With Local Auth Disabled (Default)
1. Navigate to /vaultadmin/users
2. See disabled "Add User" button with tooltip
3. See warning: "Local auth disabled - only SSO/LDAP users allowed"
4. Attempting API call returns 403 with clear message

### With Local Auth Enabled
1. Set `auth.local_enabled: true` in config.yaml
2. Navigate to /vaultadmin/users
3. See enabled "Add User" button (primary color)
4. Click button, fill form, create user successfully
5. New user appears in table with "Local" badge

### Permission Testing
```python
# Test as non-staff user
POST /api/users/ → 403 Forbidden

# Test as staff with local auth disabled
POST /api/users/ → 403 "User creation only allowed when local auth enabled"

# Test as staff with local auth enabled
POST /api/users/ → 201 Created

# Test editing JIT user
PATCH /api/users/{jit_user_id}/ → 403 "Profile managed by external IdP"

# Test deleting last superuser
DELETE /api/users/{last_super}/ → 403 "Cannot delete last superuser"
```

## Security Considerations

1. **Password Handling**: Passwords are hashed using Django's `set_password()` method
2. **Staff-Only Operations**: All create/update/delete operations require `is_staff`
3. **JIT User Protection**: External IdP users cannot be edited locally
4. **Last Superuser Protection**: System prevents deleting last superuser
5. **Configuration Check**: User creation gated by auth configuration file

## Backward Compatibility

- Existing JIT-provisioned users continue to work
- Existing staff permission checks remain
- API remains compatible (UserViewSet adds new endpoints)
- Frontend gracefully handles missing auth config

## Related Files Modified

**Backend:**
- backend/api/views.py (UserViewSet, AuthConfigView)
- backend/api/serializers.py (UserSerializer)
- backend/config/config.yaml (auth section)

**Frontend:**
- frontend/src/pages/Users.vue (template + script)

## Future Enhancements

1. Add role/group assignment during user creation
2. Add bulk user import feature
3. Add user activation/deactivation
4. Add password reset functionality
5. Add user audit log (track who created/modified users)
6. Add email verification for new users
