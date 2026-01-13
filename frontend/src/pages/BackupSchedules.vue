<template>
  <q-page class="q-pa-md">
    <q-card>
      <q-card-section>
        <div class="row items-center q-mb-sm">
          <div class="col">
            <div class="text-h4">Backup Schedules</div>
          </div>
          <div class="col-auto">
            <q-btn color="primary" label="Add Schedule" @click="showAddDialog" />
          </div>
        </div>
        <div class="row justify-end">
          <div class="text-caption text-grey">
            Set up automated backup schedules for devices
          </div>
        </div>
      </q-card-section>
      <q-separator />

      <q-card-section>
        <q-table
      :rows="schedules"
      :columns="columns"
      row-key="id"
      flat
    >
      <template v-slot:body-cell-enabled="props">
        <q-td :props="props">
          <q-badge :color="props.row.enabled ? 'positive' : 'grey'">
            {{ props.row.enabled ? 'Enabled' : 'Disabled' }}
          </q-badge>
        </q-td>
      </template>
      <template v-slot:body-cell-schedule="props">
        <q-td :props="props">
          <div v-if="props.row.schedule_type === 'daily'">
            Daily at {{ String(props.row.hour).padStart(2, '0') }}:{{ String(props.row.minute).padStart(2, '0') }}
          </div>
          <div v-else-if="props.row.schedule_type === 'weekly'">
            Weekly on {{ getDayName(props.row.day_of_week) }} at {{ String(props.row.hour).padStart(2, '0') }}:{{ String(props.row.minute).padStart(2, '0') }}
          </div>
          <div v-else-if="props.row.schedule_type === 'monthly'">
            Monthly on day {{ props.row.day_of_month }} at {{ String(props.row.hour).padStart(2, '0') }}:{{ String(props.row.minute).padStart(2, '0') }}
          </div>
          <div v-else>
            {{ props.row.cron_expression }}
          </div>
        </q-td>
      </template>
      <template v-slot:body-cell-actions="props">
        <q-td :props="props">
          <q-btn color="primary" icon="edit" label="Edit" @click="editItem(props.row)" class="q-mr-sm" />
          <q-btn color="negative" icon="delete" label="Delete" @click="deleteItem(props.row)" class="q-mr-sm" />
        </q-td>
      </template>
    </q-table>
      </q-card-section>
    </q-card>

    <q-dialog v-model="dialog">
      <q-card style="min-width: 500px">
        <q-card-section>
          <div class="text-h6">{{ editMode ? 'Edit' : 'Add' }} Backup Schedule</div>
        </q-card-section>
        <q-card-section>
          <q-input v-model="form.name" label="Name" outlined class="q-mb-md" />
          <q-input v-model="form.description" label="Description" outlined type="textarea" class="q-mb-md" />
          
          <q-select
            v-model="form.schedule_type"
            label="Schedule Type"
            :options="['daily', 'weekly', 'monthly', 'custom_cron']"
            outlined
            class="q-mb-md"
            emit-value
            map-options
          />

          <div class="row q-col-gutter-md q-mb-md">
            <div class="col-6">
              <q-input v-model.number="form.hour" label="Hour (0-23)" type="number" outlined min="0" max="23" />
            </div>
            <div class="col-6">
              <q-input v-model.number="form.minute" label="Minute (0-59)" type="number" outlined min="0" max="59" />
            </div>
          </div>

          <div v-if="form.schedule_type === 'weekly'" class="q-mb-md">
            <q-select
              v-model="form.day_of_week"
              label="Day of Week"
              :options="days"
              outlined
              emit-value
              map-options
            />
          </div>

          <div v-if="form.schedule_type === 'monthly'" class="q-mb-md">
            <q-input v-model.number="form.day_of_month" label="Day of Month (1-31)" type="number" outlined min="1" max="31" />
          </div>

          <div v-if="form.schedule_type === 'custom_cron'" class="q-mb-md">
            <q-input 
              v-model="form.cron_expression" 
              label="Cron Expression" 
              outlined
              hint="Format: minute hour day month day_of_week"
            />
          </div>

          <q-checkbox v-model="form.enabled" label="Enabled" />
        </q-card-section>

        <q-card-actions align="right">
          <q-btn flat label="Cancel" v-close-popup />
          <q-btn color="primary" label="Save" @click="save" />
        </q-card-actions>
      </q-card>
    </q-dialog>
  </q-page>
</template>

<script setup>
/**
 * Backup Schedules Admin Page Component
 * 
 * Provides interface to manage backup schedules used by Celery Beat.
 * Administrators can:
 * - Create daily, weekly, monthly, or custom cron schedules
 * - Set schedule times (hour, minute, day of week/month)
 * - Enable/disable schedules
 * - Edit and delete existing schedules
 */

import { ref, onMounted } from 'vue'
import { useQuasar } from 'quasar'
import api from '../services/api'

// ===== Component State =====

/** Quasar dialog and notification service */
const $q = useQuasar()

/** Array of backup schedule objects from API */
const schedules = ref([])

/** Dialog visibility state for add/edit form */
const dialog = ref(false)

/** Whether dialog is in edit mode (true) or add mode (false) */
const editMode = ref(false)

/**
 * Form data object for schedule creation/editing
 * 
 * Properties:
 * - name (string): Display name for schedule
 * - description (string): Purpose/notes about schedule
 * - schedule_type (string): Type of schedule (daily, weekly, monthly, custom_cron)
 * - hour (number): Hour in 24-hour format (0-23)
 * - minute (number): Minute (0-59)
 * - day_of_week (string): Day for weekly schedules (0=Sunday, 6=Saturday)
 * - day_of_month (number): Day for monthly schedules (1-31)
 * - cron_expression (string): Raw cron expression for custom schedules
 * - enabled (boolean): Whether schedule is active
 */
const form = ref({
  name: '',
  description: '',
  schedule_type: 'daily',
  hour: 0,
  minute: 0,
  day_of_week: '0',
  day_of_month: 1,
  cron_expression: '',
  enabled: true
})

/**
 * Day of week options for weekly schedule selector
 * Values: 0=Sunday through 6=Saturday
 */
const days = [
  { label: 'Sunday', value: '0' },
  { label: 'Monday', value: '1' },
  { label: 'Tuesday', value: '2' },
  { label: 'Wednesday', value: '3' },
  { label: 'Thursday', value: '4' },
  { label: 'Friday', value: '5' },
  { label: 'Saturday', value: '6' }
]

/**
 * Table Column Configuration
 * 
 * Columns:
 * - name: Schedule display name
 * - schedule: Human-readable schedule description
 * - enabled: Enabled/disabled status badge
 * - actions: Edit and delete buttons
 */
const columns = [
  { name: 'name', label: 'Name', field: 'name', align: 'left', sortable: true },
  { name: 'schedule', label: 'Schedule', field: 'schedule', align: 'left' },
  { name: 'enabled', label: 'Status', field: 'enabled', align: 'center' },
  { name: 'actions', label: 'Actions', align: 'right' }
]

// ===== Utility Functions =====

/**
 * Convert day of week number to name
 * 
 * Input:
 * - dayNum (string|number): Day number (0=Sunday, 6=Saturday)
 * 
 * Returns:
 * - string: Day name (e.g., "Monday") or empty string if invalid
 */
function getDayName(dayNum) {
  const dayNames = ['Sunday', 'Monday', 'Tuesday', 'Wednesday', 'Thursday', 'Friday', 'Saturday']
  return dayNames[parseInt(dayNum)] || ''
}

// ===== API Functions =====

/**
 * Load backup schedules from API
 * 
 * Fetches all backup schedules configured in the system.
 * Used for initial page load and after save/delete operations.
 * 
 * Error handling:
 * - Shows error notification if API fails
 */
async function loadData() {
  try {
    const response = await api.get('/backup-schedules/')
    schedules.value = response.data
  } catch (error) {
    $q.notify({ type: 'negative', message: 'Failed to load backup schedules' })
  }
}

/**
 * Show add schedule dialog
 * 
 * Resets form to default values and opens dialog in "add mode"
 * User can then fill in details and click Save to create new schedule
 */
function showAddDialog() {
  form.value = {
    name: '',
    description: '',
    schedule_type: 'daily',
    hour: 0,
    minute: 0,
    day_of_week: '0',
    day_of_month: 1,
    cron_expression: '',
    enabled: true
  }
  editMode.value = false
  dialog.value = true
}

/**
 * Edit existing schedule
 * 
 * Input:
 * - item (Object): Schedule object to edit
 * 
 * Process:
 * 1. Copy schedule data into form
 * 2. Set editMode to true
 * 3. Open dialog for editing
 */
function editItem(item) {
  form.value = { ...item }
  editMode.value = true
  dialog.value = true
}

/**
 * Save schedule (create or update)
 * 
 * Process:
 * 1. Check if in edit or add mode
 * 2. Send PUT request if editing, POST if creating
 * 3. Show success notification
 * 4. Close dialog and reload schedules
 * 
 * Error handling:
 * - Shows error notification if API fails
 */
async function save() {
  try {
    if (editMode.value) {
      await api.put(`/backup-schedules/${form.value.id}/`, form.value)
    } else {
      await api.post('/backup-schedules/', form.value)
    }
    $q.notify({ type: 'positive', message: 'Saved successfully' })
    dialog.value = false
    loadData()
  } catch (error) {
    $q.notify({ type: 'negative', message: 'Failed to save' })
  }
}

/**
 * Delete schedule with confirmation
 * 
 * Input:
 * - item (Object): Schedule to delete
 * 
 * Process:
 * 1. Show confirmation dialog
 * 2. If user confirms:
 *    - Send DELETE request to API
 *    - Show success notification
 *    - Reload schedules
 * 
 * Error handling:
 * - Shows error notification if API fails
 */
async function deleteItem(item) {
  $q.dialog({
    title: 'Confirm',
    message: `Delete schedule "${item.name}"?`,
    cancel: true
  }).onOk(async () => {
    try {
      await api.delete(`/backup-schedules/${item.id}/`)
      $q.notify({ type: 'positive', message: 'Deleted successfully' })
      loadData()
    } catch (error) {
      $q.notify({ type: 'negative', message: 'Failed to delete' })
    }
  })
}

// ===== Lifecycle Hooks =====

/**
 * Component mounted lifecycle hook
 * Loads initial backup schedules data
 */
onMounted(() => {
  loadData()
})
</script>
<style scoped>
.bg-blue-1 {
  background-color: #e3f2fd !important;
  color: #1e3a8a;
}

:deep(.body--dark) .bg-blue-1 {
  background-color: #1e3a8a !important;
  color: #90caf9;
}

:deep(.body--dark) .bg-blue-1 p,
:deep(.body--dark) .bg-blue-1 ul {
  color: #e0e0e0;
}

:deep(.body--dark) .bg-blue-1 strong {
  color: #90caf9;
}

:deep(.body--dark) .bg-blue-1 .text-primary {
  color: #90caf9 !important;
}

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