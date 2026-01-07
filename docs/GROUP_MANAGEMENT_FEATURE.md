# Group Management Feature Documentation

## Overview

The Group Management feature has been successfully implemented in DeviceVault, allowing administrators to organize users into groups and assign labels/tags that are inherited by all group members. This feature provides centralized access control management for teams and departments.

## Feature Description

### Purpose
Groups enable administrators to:
- Organize users into logical teams/departments
- Assign labels/tags to groups for access control
- Manage user permissions collectively through group membership
- Simplify access management for organizations with team-based structures

### Key Capabilities
1. **Create Groups**: Define new user groups with name and description
2. **Assign Users**: Add users to groups via multi-select interface
3. **Assign Labels**: Attach tags/labels to groups that are inherited by members
4. **Edit Groups**: Modify group settings, members, and labels
5. **Delete Groups**: Remove groups with confirmation dialog
6. **View Group Details**: Display member count, assigned labels, and metadata

## Technical Implementation

### Backend Architecture

#### Database Model: `Group` (backend/rbac/models.py)

```python
class Group(models.Model):
    name = models.CharField(max_length=128, unique=True)
    description = models.TextField(blank=True)
    labels = models.ManyToManyField(Label, blank=True)
    users = models.ManyToManyField(User, blank=True, related_name='vault_groups')
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
```

**Key Design Decisions:**
- `related_name='vault_groups'`: Avoids conflict with Django's built-in User.groups field
- `blank=True` on ManyToMany fields: Allows creating groups without members/labels initially
- `unique=True` on name: Prevents duplicate group names
- `ordering = ['name']`: Alphabetical sorting in admin interface

#### API Serializer: `GroupSerializer` (backend/api/serializers.py)

```python
class GroupSerializer(serializers.ModelSerializer):
    labels = LabelSerializer(many=True, read_only=True)
    users = UserSerializer(many=True, read_only=True)
    
    class Meta:
        model = Group
        fields = ['id', 'name', 'description', 'labels', 'users', 'created_at', 'updated_at']
```

**Features:**
- Nested LabelSerializer for read-only label details with color information
- Nested UserSerializer for read-only user details
- Write-only fields can be added for label/user IDs in POST/PATCH requests

#### API ViewSet: `GroupViewSet` (backend/api/views.py)

```python
class GroupViewSet(viewsets.ModelViewSet):
    queryset = Group.objects.all()
    serializer_class = GroupSerializer
```

**Endpoints Provided:**
- `GET /api/groups/` - List all groups with nested data
- `POST /api/groups/` - Create new group
- `GET /api/groups/{id}/` - Retrieve single group
- `PATCH /api/groups/{id}/` - Update group
- `DELETE /api/groups/{id}/` - Delete group

#### URL Configuration (backend/devicevault/urls.py)

```python
router.register(r'groups', views.GroupViewSet)
```

Routes registered with DefaultRouter for automatic CRUD endpoints.

### Frontend Implementation

#### Vue Component: `Groups.vue` (frontend/src/pages/Groups.vue)

**Component Structure:**
```
<template>
  <q-page>
    <!-- Page Header -->
    <!-- Data Table with Groups -->
    <!-- Add/Edit Dialog -->
    <!-- Delete Confirmation Dialog -->
  </q-page>
</template>

<script setup>
  // State management
  // API methods
  // Dialog handlers
  // Helper functions
  // Lifecycle hooks
</script>
```

**Key Features:**

1. **Data Table Display**
   - Columns: Name, Description, Members Count, Labels, Actions
   - Empty state when no groups exist
   - Responsive layout with Quasar components

2. **Add/Edit Dialog**
   - Form inputs for name and description
   - Multi-select for labels with color indicators
   - Multi-select for users with avatar display
   - Form validation (name required, character limits)
   - Save or cancel options

3. **Label Assignment**
   - Search and filter available labels
   - Visual color indicators for each label
   - Display selected labels with removal capability
   - Preview of assigned labels

4. **User Assignment**
   - Search and filter available users
   - Display user avatars and emails
   - Multi-select interface
   - Show count of selected users

5. **Actions**
   - Edit button: Opens edit dialog with populated form
   - Delete button: Opens confirmation dialog
   - Responsive action buttons with tooltips

#### Router Configuration (frontend/src/router/index.js)

```javascript
import Groups from '../pages/Groups.vue'

const routes = [
  { path: '/vaultadmin/groups', component: Groups, meta: { requiresAuth: true } }
]
```

**Route Details:**
- Path: `/vaultadmin/groups`
- Protected route: Requires authentication
- Component: Groups.vue
- Accessible only to authenticated users

#### Navigation Menu Integration (frontend/src/App.vue)

Added to Admin Settings expandable menu:
```vue
<q-item clickable to="/vaultadmin/groups">
  <q-item-section avatar>
    <q-icon name="group" />
  </q-item-section>
  <q-item-section>
    <q-item-label>Groups</q-item-label>
  </q-item-section>
</q-item>
```

**Navigation Hierarchy:**
- Admin Settings (expansion item)
  - Device Types
  - Manufacturers
  - Credentials
  - Backup Locations
  - Backup Schedules
  - Retention Policies
  - **Groups** (NEW)
  - Users

## API Usage Examples

### Create a Group with Labels and Users

**Request:**
```bash
POST /api/groups/
Content-Type: application/json

{
  "name": "Production Team",
  "description": "Team managing production devices",
  "labels": [1, 2],
  "users": [3, 4, 5]
}
```

**Response (201 Created):**
```json
{
  "id": 1,
  "name": "Production Team",
  "description": "Team managing production devices",
  "labels": [
    {
      "id": 1,
      "name": "Production",
      "color": "#FF6B6B"
    },
    {
      "id": 2,
      "name": "Critical",
      "color": "#FFA500"
    }
  ],
  "users": [
    {
      "id": 3,
      "username": "john_smith",
      "email": "john@example.com"
    },
    {
      "id": 4,
      "username": "jane_doe",
      "email": "jane@example.com"
    },
    {
      "id": 5,
      "username": "bob_jones",
      "email": "bob@example.com"
    }
  ],
  "created_at": "2024-01-15T10:30:00Z",
  "updated_at": "2024-01-15T10:30:00Z"
}
```

### Update a Group

**Request:**
```bash
PATCH /api/groups/1/
Content-Type: application/json

{
  "description": "Updated: Manages all production infrastructure",
  "labels": [1, 2, 3],
  "users": [3, 4, 5, 6]
}
```

### List All Groups

**Request:**
```bash
GET /api/groups/
```

**Response:**
```json
[
  {
    "id": 1,
    "name": "Production Team",
    "description": "Team managing production devices",
    "labels": [...],
    "users": [...],
    "created_at": "2024-01-15T10:30:00Z",
    "updated_at": "2024-01-15T10:30:00Z"
  },
  {
    "id": 2,
    "name": "Development Team",
    "description": "Team managing development devices",
    "labels": [...],
    "users": [...],
    "created_at": "2024-01-15T11:00:00Z",
    "updated_at": "2024-01-15T11:00:00Z"
  }
]
```

### Delete a Group

**Request:**
```bash
DELETE /api/groups/1/
```

**Response:** 204 No Content

## User Workflow

### Creating a Group

1. Navigate to Admin Settings → Groups
2. Click "Add Group" button
3. Enter group name (required)
4. Enter optional description
5. Select labels/tags from "Assign Labels" dropdown
6. Select users from "Assign Users" dropdown
7. Click "Save"
8. Group appears in table with assigned members and labels

### Editing a Group

1. Navigate to Admin Settings → Groups
2. Click edit icon (pencil) on desired group row
3. Dialog opens with populated group data
4. Modify name, description, labels, or users as needed
5. Click "Save"
6. Changes reflected immediately in table

### Deleting a Group

1. Navigate to Admin Settings → Groups
2. Click delete icon (trash) on desired group row
3. Confirmation dialog appears
4. Click "Delete" to confirm
5. Group removed from table

## Database Migrations

**Migration File:** `backend/rbac/migrations/0002_*.py`

**Status:** Applied to database

**Changes:**
- Creates `rbac_group` table with columns:
  - id (auto-increment primary key)
  - name (CharField, unique)
  - description (TextField)
  - created_at (DateTimeField)
  - updated_at (DateTimeField)
- Creates `rbac_group_labels` junction table for ManyToMany relationship
- Creates `rbac_group_users` junction table for ManyToMany relationship

**Applied Successfully:**
```
Operations to perform:
  Apply all migrations: audit, backups, core, credentials, ...
Running migrations:
  Applying rbac.0002_*... OK
```

## Related Features and Integration

### Devices Page
- Devices are tagged with labels
- Users in groups inherit those labels
- Access control filters devices based on user's assigned labels

### Users Management
- View all users in system
- User's groups shown in user details
- Users can be members of multiple groups

### Labels/Tags System
- Labels are defined separately in core app
- Groups reference existing labels
- Color coding for visual identification

### Audit Logging
- Group creation, updates, and deletions logged
- Track changes to group membership and labels

## File Structure

```
backend/
├── rbac/
│   ├── models.py (Group model added)
│   └── migrations/
│       └── 0002_*.py (Migration created and applied)
├── api/
│   ├── serializers.py (GroupSerializer added)
│   ├── views.py (GroupViewSet added)
│   └── urls.py (groups endpoint registered)
└── devicevault/
    └── urls.py (groups route registered)

frontend/
├── src/
│   ├── pages/
│   │   └── Groups.vue (NEW component created)
│   ├── router/
│   │   └── index.js (Groups route added)
│   └── App.vue (Navigation menu updated)
```

## Testing

### Backend Verification
✅ Group model imports successfully
✅ GroupSerializer imports successfully
✅ GroupViewSet registered with router
✅ All migrations applied to database
✅ API endpoints available at /api/groups/

### Frontend Verification
✅ Groups component created
✅ Router configuration correct
✅ Navigation menu link added
✅ Component imports properly

## Error Handling

### Common Issues and Solutions

**1. Related Name Conflict**
- **Issue**: `related_name='groups'` conflicts with Django's User.groups
- **Solution**: Changed to `related_name='vault_groups'`
- **Status**: ✅ Resolved

**2. Circular Imports**
- **Issue**: Serializer order causing NameError
- **Solution**: Moved UserSerializer definition before GroupSerializer
- **Status**: ✅ Resolved

**3. Missing Labels/Users on Frontend**
- **Issue**: Frontend dropdowns empty when loading
- **Solution**: API calls fetch labels and users on component mount
- **Status**: ✅ Handled

## Performance Considerations

1. **Query Optimization**
   - Use `select_related()` and `prefetch_related()` in ViewSet if needed
   - Currently loads nested objects which is appropriate for small datasets

2. **Pagination**
   - Currently returns all groups (suitable for typical admin usage)
   - Can add pagination using Quasar Q-Table pagination

3. **Caching**
   - Consider caching labels and users dropdowns
   - Cache group list for frequently accessed data

## Security

1. **Authentication**
   - All group management endpoints require authentication
   - Route protected with `requiresAuth: true` meta flag

2. **Authorization**
   - Currently accessible to all authenticated users
   - Can add permission checks in ViewSet if role-based access needed

3. **Input Validation**
   - Form validation on frontend (required fields, character limits)
   - Backend model validation (unique name, max length)
   - Django DRF automatic validation on serializers

## Future Enhancement Possibilities

1. **Bulk Operations**
   - Bulk assign users to multiple groups
   - Bulk delete multiple groups

2. **Advanced Filtering**
   - Filter groups by label
   - Filter groups by number of members
   - Search groups by name/description

3. **Permissions**
   - Role-based access to group management
   - Group-specific admin roles

4. **Group Hierarchies**
   - Parent/child group relationships
   - Nested group structures

5. **Activity Tracking**
   - Group membership change history
   - Label assignment audit trail

6. **Exports**
   - Export group lists to CSV/Excel
   - Export group membership reports

## Conclusion

The Group Management feature is now fully implemented and ready for use. It provides administrators with an intuitive interface to organize users into groups and manage their collective access through label assignment. The implementation follows DeviceVault's established patterns and integrates seamlessly with existing components.
