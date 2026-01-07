<template>
  <q-page class="q-pa-md">
    <div class="row justify-between items-center q-mb-md">
      <div class="text-h4">Backup Schedules</div>
      <q-btn color="primary" label="Add Schedule" @click="showAddDialog" />
    </div>

    <q-card class="q-mb-lg bg-blue-1">
      <q-card-section>
        <div class="text-subtitle2 text-primary q-mb-md"><strong>About Backup Schedules</strong></div>
        <p class="q-my-sm">Backup tasks will be added to the Celery queue at the specified time and will be processed in order. This uses Celery Beat as the scheduling engine, with backup times and schedules stored in the configuration database.</p>
        <p class="q-my-sm"><strong>Key Points:</strong></p>
        <ul class="q-pl-md q-my-sm">
          <li>Schedules are processed by Celery Beat, a distributed task scheduler</li>
          <li>Multiple backups will be queued and processed sequentially</li>
          <li>Times are in the server's timezone</li>
          <li>Only enabled schedules will process backups</li>
          <li>Devices marked as "Example Data" will be excluded from backup processing</li>
        </ul>
      </q-card-section>
    </q-card>

    <q-table
      :rows="schedules"
      :columns="columns"
      row-key="id"
      flat
      bordered
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
          <q-btn flat dense color="primary" icon="edit" @click="editItem(props.row)" class="q-mr-sm" />
          <q-btn flat dense color="negative" icon="delete" @click="deleteItem(props.row)" />
        </q-td>
      </template>
    </q-table>

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
import { ref, onMounted } from 'vue'
import { useQuasar } from 'quasar'
import api from '../services/api'

const $q = useQuasar()
const schedules = ref([])
const dialog = ref(false)
const editMode = ref(false)
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

const days = [
  { label: 'Sunday', value: '0' },
  { label: 'Monday', value: '1' },
  { label: 'Tuesday', value: '2' },
  { label: 'Wednesday', value: '3' },
  { label: 'Thursday', value: '4' },
  { label: 'Friday', value: '5' },
  { label: 'Saturday', value: '6' }
]

const columns = [
  { name: 'name', label: 'Name', field: 'name', align: 'left', sortable: true },
  { name: 'schedule', label: 'Schedule', field: 'schedule', align: 'left' },
  { name: 'enabled', label: 'Status', field: 'enabled', align: 'center' },
  { name: 'actions', label: 'Actions', align: 'center' }
]

function getDayName(dayNum) {
  const dayNames = ['Sunday', 'Monday', 'Tuesday', 'Wednesday', 'Thursday', 'Friday', 'Saturday']
  return dayNames[parseInt(dayNum)] || ''
}

async function loadData() {
  try {
    const response = await api.get('/backup-schedules/')
    schedules.value = response.data
  } catch (error) {
    $q.notify({ type: 'negative', message: 'Failed to load backup schedules' })
  }
}

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

function editItem(item) {
  form.value = { ...item }
  editMode.value = true
  dialog.value = true
}

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
</style>