<template>
  <q-page class="q-pa-md">
    <q-card>
      <!-- Page Header -->
      <q-card-section>
        <div class="row items-center q-mb-sm">
          <div class="col">
            <div class="text-h4">Device Groups</div>
          </div>
          <div class="col-auto">
            <q-btn
              v-if="isAdmin"
              color="primary"
              label="Add Device Group"
              icon="add"
              @click="openAddGroupDialog"
            />
          </div>
        </div>
        <div class="row justify-end">
          <div class="text-caption text-grey">
            Summary of device groups. Roles are managed automatically.
          </div>
        </div>
      </q-card-section>
      <q-separator />

      <!-- Device Groups Table -->
      <q-card-section>
        <q-linear-progress
          v-if="loading"
          indeterminate
          color="primary"
        />
        
        <q-table
        :rows="deviceGroups"
        :columns="columns"
        row-key="id"
        flat
      >
        <!-- Name Column -->
        <template #body-cell-name="props">
          <q-td :props="props" class="text-weight-bold">
            {{ props.row.name }}
          </q-td>
        </template>

        <!-- Description Column -->
        <template #body-cell-description="props">
          <q-td :props="props">
            <span v-if="props.row.description" class="text-caption">
              {{ props.row.description }}
            </span>
            <span v-else class="text-grey-6 italic">No description</span>
          </q-td>
        </template>

        <!-- Created Date Column -->
        <template #body-cell-created_at="props">
          <q-td :props="props">
            <span class="text-caption">
              {{ formatDate(props.row.created_at) }}
            </span>
          </q-td>
        </template>

        <!-- Updated Date Column -->
        <template #body-cell-updated_at="props">
          <q-td :props="props">
            <span class="text-caption">
              {{ formatDate(props.row.updated_at) }}
            </span>
          </q-td>
        </template>

        <!-- Actions Column -->
        <template #body-cell-actions="props">
          <q-td :props="props">
            <q-btn
              v-if="isAdmin"
              color="primary"
              icon="edit"
              label="Edit"
              @click="openEditGroupDialog(props.row)"
              class="q-mr-sm"
            />
            <q-btn
              v-if="isAdmin"
              color="negative"
              icon="delete"
              label="Delete"
              @click="deleteGroup(props.row)"
              class="q-mr-sm"
            />
          </q-td>
        </template>
      </q-table>
      </q-card-section>
    </q-card>

    <!-- Add/Edit Device Group Dialog -->
    <q-dialog v-model="showGroupDialog" @hide="resetGroupForm">
      <q-card style="min-width: 400px">
        <q-card-section class="row items-center q-pb-none">
          <div class="text-h6">{{ editingGroup ? 'Edit Device Group' : 'Add Device Group' }}</div>
          <q-space />
          <q-btn icon="close" flat round dense @click="showGroupDialog = false" />
        </q-card-section>

        <q-card-section>
          <q-form @submit="saveGroup">
            <q-input
              v-model="groupForm.name"
              label="Group Name"
              outlined
              dense
              class="q-mb-md"
              rules="required"
            />

            <q-input
              v-model="groupForm.description"
              label="Description"
              outlined
              dense
              type="textarea"
              rows="3"
              class="q-mb-md"
            />

            <div class="row q-gutter-md">
              <q-btn
                label="Cancel"
                color="primary"
                flat
                @click="showGroupDialog = false"
              />
              <q-btn
                label="Save"
                color="primary"
                type="submit"
              />
            </div>
          </q-form>
        </q-card-section>
      </q-card>
    </q-dialog>

    
  </q-page>
</template>

<script setup>
/**
 * Device Groups Management Page Component
 * 
 * Allows administrators to manage device groups and their roles.
 * Users with access to a device group can see role assignments.
 * 
 * Features:
 * - View all accessible device groups
 * - Create/edit device groups (admin only)
 * - Roles are created and renamed automatically in backend
 */

import { ref, onMounted } from 'vue'
import { useQuasar } from 'quasar'
import api from '../services/api'
import { formatDate } from '../utils/timezone'

// ===== Component State =====

const $q = useQuasar()

const deviceGroups = ref([])
const loading = ref(false)
const isAdmin = ref(false)

// Dialog states
const showGroupDialog = ref(false)
// No role dialogs in summary-only view

// Form states
const editingGroup = ref(null)

const groupForm = ref({
  name: '',
  description: ''
})

// Summary-only: no role/user assignment state

/**
 * Table Column Configuration
 */
const columns = [
  { name: 'name', label: 'Name', field: 'name', align: 'left', sortable: true },
  { name: 'description', label: 'Description', field: 'description', align: 'left' },
  { name: 'created_at', label: 'Created', field: 'created_at', align: 'left' },
  { name: 'updated_at', label: 'Updated', field: 'updated_at', align: 'left' },
  { name: 'actions', label: 'Actions', align: 'right' }
]

/**
 * Computed: Permission options for role creation
 */
// No permission options in summary-only view

/**
 * Computed: Users not yet assigned to selected role
 */
// No user-role assignment in summary-only view

// ===== API Functions =====

/**
 * Load device groups
 */
async function loadDeviceGroups() {
  loading.value = true
  try {
    const response = await api.get('/device-groups/')
    deviceGroups.value = response.data
  } catch (error) {
    $q.notify({ type: 'negative', message: 'Failed to load device groups' })
  } finally {
    loading.value = false
  }
}

/**
 * Load available permissions
 */
// No permissions/users needed in summary-only view

/**
 * Save device group (create or update)
 */
async function saveGroup() {
  try {
    if (editingGroup.value) {
      await api.patch(`/device-groups/${editingGroup.value.id}/`, groupForm.value)
      $q.notify({ type: 'positive', message: 'Device group updated' })
    } else {
      await api.post('/device-groups/', groupForm.value)
      $q.notify({ type: 'positive', message: 'Device group created' })
    }
    showGroupDialog.value = false
    loadDeviceGroups()
  } catch (error) {
    $q.notify({ type: 'negative', message: 'Failed to save device group' })
  }
}

/**
 * Delete device group
 */
async function deleteGroup(group) {
  $q.dialog({
    title: 'Delete Device Group',
    message: `Are you sure you want to delete "${group.name}"? Deletion is blocked if related roles have members.`,
    cancel: true
  }).onOk(async () => {
    try {
      await api.delete(`/device-groups/${group.id}/`)
      $q.notify({ type: 'positive', message: 'Device group deleted' })
      loadDeviceGroups()
    } catch (error) {
      let msg = 'Failed to delete device group'
      const data = error && error.response && error.response.data
      if (typeof data === 'string') {
        msg = data
      } else if (data && typeof data === 'object') {
        if (data.detail) {
          msg = Array.isArray(data.detail) ? data.detail.join(', ') : data.detail
        } else {
          const firstKey = Object.keys(data)[0]
          if (firstKey && data[firstKey]) {
            const val = data[firstKey]
            msg = Array.isArray(val) ? val.join(', ') : String(val)
          }
        }
      }
      $q.notify({ type: 'negative', message: msg })
    }
  })
}

// ===== Dialog Methods =====

function openAddGroupDialog() {
  editingGroup.value = null
  groupForm.value = { name: '', description: '' }
  showGroupDialog.value = true
}

function openEditGroupDialog(group) {
  editingGroup.value = group
  groupForm.value = { ...group }
  showGroupDialog.value = true
}

// Summary-only: no role management dialogs

function resetGroupForm() {
  editingGroup.value = null
  groupForm.value = { name: '', description: '' }
}

// No role/user forms to reset

// ===== Lifecycle =====

onMounted(async () => {
  const user = JSON.parse(localStorage.getItem('user') || '{}')
  isAdmin.value = (user.is_staff || user.is_superuser) || false

  await loadDeviceGroups()
})
</script>

<style scoped>
:deep(.q-table) {
  font-size: 1.5rem;
}

:deep(.q-table tbody td) {
  padding: 12px 8px;
  font-size: 1.4rem;
}

:deep(.q-table thead th) {
  font-size: 1.5rem;
  font-weight: 600;
}

:deep(.q-table .q-badge) {
  font-size: 1.2rem;
  padding: 6px 12px;
  min-height: 2.5rem;
  display: inline-flex;
  align-items: center;
  justify-content: center;
}
</style>
