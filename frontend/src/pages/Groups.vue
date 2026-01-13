<!--
Groups Management Page Component

Purpose:
This component provides a comprehensive interface for managing user groups in the DeviceVault system.
Administrators can create, edit, and delete groups, as well as assign users and device group roles.
Groups allow for collective role management - all users in a group inherit device group roles assigned to that group.

Features:
- Display list of all groups in a data table
- Create new groups with name
- Edit existing groups and modify their settings
- Delete groups with confirmation
- Assign device group roles to groups
- Assign users to groups (multi-select from available users)
- Real-time updates through Django REST API endpoints

API Integration:
- GET /api/groups/ - Fetch all groups with nested device group permissions and users
- POST /api/groups/ - Create new group
- PATCH /api/groups/{id}/ - Update group including user and permission assignments
- DELETE /api/groups/{id}/ - Delete group
- GET /api/device-group-permissions/ - Fetch available device group permissions
- GET /api/users/ - Fetch available users for group membership

User Workflow:
1. View all groups in table format
2. Click "Add Group" button to create new group
3. Fill in group name, select users, and select device group permissions
4. Save group or cancel
5. Click edit icon to modify existing group
6. Click delete icon to remove group (with confirmation)
7. See real-time updates reflected in table

Design Pattern:
Follows component composition pattern with separated concerns:
- Dialog components for add/edit operations
- Table component for display and actions
- Data management through component state
- API calls through central service

Related Components:
- DeviceGroups.vue (manage device groups and roles)
- Users.vue (manage users and their assignments)
- Devices.vue (devices controlled by group permissions)
-->

<template>
  <q-page class="q-pa-md">
    <q-card>
      <!-- Page Header -->
      <q-card-section>
        <div class="row items-center q-mb-sm">
          <div class="col">
            <div class="text-h5">Groups</div>
          </div>
          <div class="col-auto">
            <q-btn
              color="primary"
              label="Add Group"
              icon="add"
              @click="openAddDialog"
            />
          </div>
        </div>
        <div class="row justify-end">
          <div class="text-caption text-grey">
            Manage user groups and assign device group permissions
          </div>
        </div>
      </q-card-section>
      <q-separator />

      <!-- Groups Data Table -->
      <q-card-section>
        <q-linear-progress
          v-if="loading"
          indeterminate
          color="primary"
        />
        
        <q-table
        :rows="groups"
        :columns="columns"
        row-key="id"
        flat
        class="admin-table"
      >
        <!-- Name Column -->
        <template #body-cell-name="props">
          <q-td :props="props" class="text-weight-bold">
            {{ props.row.name }}
          </q-td>
        </template>

        <!-- Members Count Column -->
        <template #body-cell-members="props">
          <q-td :props="props" class="text-center">
            <q-badge
              color="primary"
              text-color="white"
              class="q-px-md q-py-xs text-subtitle2"
            >
              {{ props.row.users.length }}
            </q-badge>
          </q-td>
        </template>

        <!-- Device Group Permissions Column -->
        <template #body-cell-roles="props">
          <q-td :props="props">
            <div class="column q-gutter-xs">
              <q-btn
                v-for="perm in normalizePermissions(props.row)"
                :key="perm.id"
                :label="perm.name"
                rounded
                outline
                dense
                no-caps
                color="primary"
                size="md"
                style="font-size: 1.1rem"
              />
              <span v-if="normalizePermissions(props.row).length === 0" class="text-grey-6 italic">No permissions</span>
            </div>
          </q-td>
        </template>

        <!-- Actions Column -->
        <template #body-cell-actions="props">
          <q-td :props="props" class="text-center">
            <q-btn
              icon="edit"
              label="Edit"
              color="primary"
              @click="openEditDialog(props.row)"
              class="q-mr-sm"
            >
              <q-tooltip>Edit Group</q-tooltip>
            </q-btn>
            <q-btn
              icon="delete"
              label="Delete"
              color="negative"
              @click="confirmDelete(props.row)"
              class="q-mr-sm"
            >
              <q-tooltip>Delete Group</q-tooltip>
            </q-btn>
          </q-td>
        </template>

        <!-- Empty State -->
        <template #no-data>
          <div class="full-width row flex-center text-grey-6 q-py-lg">
            <div class="text-center">
              <q-icon size="lg" name="groups" />
              <p class="q-ma-md">No groups found. Create one to get started.</p>
            </div>
          </div>
        </template>
      </q-table>
      </q-card-section>
    </q-card>

    <!-- Add/Edit Group Dialog -->
    <q-dialog v-model="dialogOpen" @hide="resetForm">
      <q-card style="width: 500px; max-width: 90vw">
        <!-- Dialog Header -->
        <q-card-section class="row items-center q-pb-none">
          <div class="text-h6">{{ isEditing ? 'Edit Group' : 'Create New Group' }}</div>
          <q-space />
          <q-btn icon="close" flat round dense @click="dialogOpen = false" />
        </q-card-section>

        <!-- Dialog Content -->
        <q-card-section class="q-gutter-md">
          <!-- Group Name -->
          <q-input
            v-model="formData.name"
            label="Group Name"
            outlined
            dense
            :rules="[
              val => !!val || 'Group name is required',
              val => val.length <= 150 || 'Name must be 150 characters or less'
            ]"
            @keyup.enter="saveGroup"
          />

          <!-- Users Assignment -->
          <div>
            <label class="text-subtitle2 q-mb-sm">Assign Users</label>
            <p class="text-caption text-grey-6 q-ma-none q-mb-md">
              Select which users should be members of this group
            </p>
            <q-select
              v-model="formData.selectedUsers"
              :options="availableUsers"
              option-value="id"
              option-label="username"
              multiple
              outlined
              dense
              emit-value
              map-options
            >
              <!-- Custom User Display -->
              <template #prepend>
                <q-icon name="people" />
              </template>

              <!-- User Options -->
              <template #option="scope">
                <q-item v-bind="scope.itemProps">
                  <q-item-section avatar>
                    <q-avatar
                      :name="scope.opt.username"
                      color="primary"
                      text-color="white"
                      size="sm"
                    />
                  </q-item-section>
                  <q-item-section>
                    <q-item-label>{{ scope.opt.username }}</q-item-label>
                    <q-item-label caption v-if="scope.opt.email">
                      {{ scope.opt.email }}
                    </q-item-label>
                  </q-item-section>
                </q-item>
              </template>

              <!-- Selected User Display -->
              <template #selected-item="scope">
                <q-chip
                  v-if="scope.opt"
                  removable
                  dense
                  :avatar="scope.opt.username.charAt(0).toUpperCase()"
                  @remove="scope.removeAtIndex(scope.index)"
                >
                  {{ scope.opt.username }}
                </q-chip>
              </template>
            </q-select>

            <!-- Selected Users Count -->
            <div v-if="formData.selectedUsers.length > 0" class="q-mt-sm">
              <p class="text-caption text-grey-7">
                {{ formData.selectedUsers.length }} user(s) selected
              </p>
            </div>
          </div>

          <!-- Device Group Permissions Assignment -->
          <div>
            <label class="text-subtitle2 q-mb-sm">Assign Device Group Permissions</label>
            <p class="text-caption text-grey-6 q-ma-none q-mb-md">
              Select device group permissions to assign to this group. Members will inherit these permissions.
            </p>
            <q-select
              v-model="formData.selectedPermissions"
              :options="availablePermissions"
              option-value="id"
              option-label="name"
              multiple
              outlined
              dense
              emit-value
              map-options
            >
              <!-- Custom Role Display -->
              <template #prepend>
                <q-icon name="security" />
              </template>

              <!-- Role Options -->
              <template #option="scope">
                <q-item v-bind="scope.itemProps">
                  <q-item-section>
                    <q-item-label>{{ scope.opt.name }}</q-item-label>
                    <q-item-label caption>{{ scope.opt.device_group_name }}</q-item-label>
                  </q-item-section>
                </q-item>
              </template>

              <!-- Selected Permission Display -->
              <template #selected-item="scope">
                <q-chip
                  v-if="scope.opt"
                  removable
                  dense
                  color="primary"
                  text-color="white"
                  @remove="scope.removeAtIndex(scope.index)"
                >
                  {{ scope.opt.name }}
                </q-chip>
              </template>
            </q-select>

            <!-- Selected Permissions Count -->
            <div v-if="formData.selectedPermissions.length > 0" class="q-mt-sm">
              <p class="text-caption text-grey-7">
                {{ formData.selectedPermissions.length }} permission(s) selected
              </p>
            </div>
          </div>
        </q-card-section>

        <!-- Dialog Actions -->
        <q-card-section class="row items-center justify-end q-gutter-sm">
          <q-btn
            label="Cancel"
            color="grey-7"
            unelevated
            @click="dialogOpen = false"
          />
          <q-btn
            label="Save"
            color="primary"
            unelevated
            @click="saveGroup"
            :loading="saving"
          />
        </q-card-section>
      </q-card>
    </q-dialog>

    <!-- Delete Confirmation Dialog -->
    <q-dialog v-model="deleteDialogOpen">
      <q-card>
        <q-card-section class="row items-center q-pb-none">
          <q-icon name="warning" color="negative" size="lg" />
          <span class="q-ml-md text-h6">Delete Group?</span>
          <q-space />
          <q-btn icon="close" flat round dense @click="deleteDialogOpen = false" />
        </q-card-section>

        <q-card-section>
          <p v-if="selectedGroup">
            Are you sure you want to delete the group "<strong>{{ selectedGroup.name }}</strong>"?
            This action cannot be undone.
          </p>
        </q-card-section>

        <q-card-section class="row items-center justify-end q-gutter-sm">
          <q-btn
            label="Cancel"
            color="grey-7"
            unelevated
            @click="deleteDialogOpen = false"
          />
          <q-btn
            label="Delete"
            color="negative"
            unelevated
            @click="deleteGroup"
            :loading="deleting"
          />
        </q-card-section>
      </q-card>
    </q-dialog>
  </q-page>
</template>

<script>
import { ref, onMounted } from 'vue'
import { useQuasar } from 'quasar'
import API from '../services/api'

export default {
  name: 'Groups',
  
  setup() {
    // ===== State Variables =====
    
    // Data collections
    const groups = ref([])
    const availableUsers = ref([])
    const availablePermissions = ref([])
    
    // UI state
    const loading = ref(false)
    const saving = ref(false)
    const deleting = ref(false)
    const dialogOpen = ref(false)
    const deleteDialogOpen = ref(false)
    const isEditing = ref(false)
    
    // Selected items
    const selectedGroup = ref(null)
    
    // Form data
    const formData = ref({
      name: '',
      selectedUsers: [],
      selectedPermissions: []
    })

    // Normalize permissions for display: only show device group permissions
    // Groups page is superuser-only, so show all device group permissions without filtering
    const normalizePermissions = (row) => {
      const list = Array.isArray(row?.device_group_permissions) ? row.device_group_permissions : []
      return list.filter(Boolean)
    }
    
    // Table columns definition
    const columns = [
      {
        name: 'name',
        label: 'Name',
        field: 'name',
        align: 'left'
      },
      {
        name: 'members',
        label: 'Members',
        field: 'members',
        align: 'center',
        sortable: true
      },
      {
        name: 'roles',
        label: 'Device Group Permissions',
        field: 'roles',
        align: 'left'
      },
      {
        name: 'actions',
        label: 'Actions',
        field: 'actions',
        align: 'right'
      }
    ]
    
    const $q = useQuasar()
    
    // ===== API Methods =====
    
    /**
     * Fetch all groups from API
     */
    const fetchGroups = async () => {
      try {
        loading.value = true
        const response = await API.get('/groups/')
        groups.value = response.data
      } catch (error) {
        console.error('Error fetching groups:', error)
        $q.notify({
          type: 'negative',
          message: 'Failed to load groups',
          position: 'top'
        })
      } finally {
        loading.value = false
      }
    }
    
    /**
     * Fetch all available users for group membership
     */
    const fetchUsers = async () => {
      try {
        const response = await API.get('/users/')
        availableUsers.value = response.data
      } catch (error) {
        console.error('Error fetching users:', error)
      }
    }

    /**

     * Fetch all available device group permissions
     */
    const fetchPermissions = async () => {
      try {
        const response = await API.get('/device-group-permissions/')
        availablePermissions.value = response.data
      } catch (error) {
        console.error('Error fetching permissions:', error)
      }
    }
    
    /**
     * Create new group via API
     */
    const createGroup = async () => {
      try {
        saving.value = true
        const payload = {
          name: formData.value.name,
          user_ids: formData.value.selectedUsers,
          permission_ids: formData.value.selectedPermissions
        }
        await API.post('/groups/', payload)
        
        $q.notify({
          type: 'positive',
          message: 'Group created successfully',
          position: 'top'
        })
        
        await fetchGroups()
        dialogOpen.value = false
        resetForm()
      } catch (error) {
        console.error('Error creating group:', error)
        $q.notify({
          type: 'negative',
          message: 'Failed to create group',
          position: 'top'
        })
      } finally {
        saving.value = false
      }
    }
    
    /**
     * Update existing group via API
     */
    const updateGroup = async () => {
      try {
        saving.value = true
        const payload = {
          name: formData.value.name,
          user_ids: formData.value.selectedUsers,
          permission_ids: formData.value.selectedPermissions
        }
        await API.patch(`/groups/${selectedGroup.value.id}/`, payload)
        
        $q.notify({
          type: 'positive',
          message: 'Group updated successfully',
          position: 'top'
        })
        
        await fetchGroups()
        dialogOpen.value = false
        resetForm()
      } catch (error) {
        console.error('Error updating group:', error)
        $q.notify({
          type: 'negative',
          message: 'Failed to update group',
          position: 'top'
        })
      } finally {
        saving.value = false
      }
    }
    
    /**
     * Delete group via API
     */
    const deleteGroup = async () => {
      try {
        deleting.value = true
        
        await API.delete(`/groups/${selectedGroup.value.id}/`)
        
        $q.notify({
          type: 'positive',
          message: 'Group deleted successfully',
          position: 'top'
        })
        
        await fetchGroups()
        deleteDialogOpen.value = false
        selectedGroup.value = null
      } catch (error) {
        console.error('Error deleting group:', error)
        $q.notify({
          type: 'negative',
          message: 'Failed to delete group',
          position: 'top'
        })
      } finally {
        deleting.value = false
      }
    }
    
    // ===== Dialog Methods =====
    
    /**
     * Open add group dialog
     */
    const openAddDialog = () => {
      isEditing.value = false
      selectedGroup.value = null
      resetForm()
      dialogOpen.value = true
    }
    
    /**
     * Open edit group dialog
     */
    const openEditDialog = (group) => {
      isEditing.value = true
      selectedGroup.value = group
      
      // Populate form with existing data
      formData.value.name = group.name
      formData.value.selectedUsers = group.users.map(u => u.id)
      formData.value.selectedPermissions = group.device_group_permissions.map(p => p.id)
      
      dialogOpen.value = true
    }
    
    /**
     * Reset form data to initial state
     */
    const resetForm = () => {
      formData.value = {
        name: '',
        selectedUsers: [],
        selectedPermissions: []
      }
    }
    
    /**
     * Save group (create or update)
     */
    const saveGroup = async () => {
      // Validate form
      if (!formData.value.name.trim()) {
        $q.notify({
          type: 'warning',
          message: 'Please enter a group name',
          position: 'top'
        })
        return
      }
      
      if (isEditing.value) {
        await updateGroup()
      } else {
        await createGroup()
      }
    }
    
    /**
     * Confirm group deletion
     */
    const confirmDelete = (group) => {
      selectedGroup.value = group
      deleteDialogOpen.value = true
    }
    
    // ===== Lifecycle Hooks =====
    
    /**
     * Initialize component
     */
    onMounted(async () => {
      await Promise.all([
        fetchGroups(),
        fetchUsers(),
        fetchPermissions()
      ])
    })
    
    return {
      // Data
      groups,
      availableUsers,
      availablePermissions,
      columns,
      formData,
      selectedGroup,
      normalizePermissions,
      
      // UI State
      loading,
      saving,
      deleting,
      dialogOpen,
      deleteDialogOpen,
      isEditing,
      
      // Methods
      openAddDialog,
      openEditDialog,
      resetForm,
      saveGroup,
      confirmDelete,
      deleteGroup
    }
  }
}
</script>
