<template>
  <q-page class="q-pa-md">
    <q-card>
      <q-card-section>
        <div class="row items-center">
          <div class="col">
            <div class="text-h4">Backups for {{ deviceName }}</div>
            <div class="text-caption text-grey">View and compare device backup configurations</div>
          </div>
          <div class="col-auto">
            <q-btn
              color="primary"
              label="Compare Selected"
              icon="compare_arrows"
              :disabled="!selectedA || !selectedB || comparePending"
              @click="navigateToCompare"
              :loading="comparePending"
            />
          </div>
        </div>
      </q-card-section>
      
      <q-separator />
      
      <q-card-section v-if="loadingBackups" class="text-center q-py-lg">
        <q-spinner color="primary" size="50px" />
        <div class="text-grey q-mt-md">Loading backups...</div>
      </q-card-section>

      <q-card-section v-else-if="backups.length === 0" class="text-center q-py-lg">
        <div class="text-grey">No backups found for this device</div>
      </q-card-section>

      <q-card-section v-else>
        <q-table
          :rows="backups"
          :columns="columns"
          row-key="id"
          flat
          class="backup-table"
          :pagination="pagination"
          :rows-per-page-options="[20, 50, 100, 0]"
        >
          <template v-slot:body-cell-select-a="props">
            <q-td :props="props">
              <q-radio
                v-if="props.row.status === 'success'"
                v-model="selectedA"
                :val="props.row.id"
                color="primary"
              />
            </q-td>
          </template>

          <template v-slot:body-cell-select-b="props">
            <q-td :props="props">
              <q-radio
                v-if="props.row.status === 'success'"
                v-model="selectedB"
                :val="props.row.id"
                color="primary"
              />
            </q-td>
          </template>

          <template v-slot:body-cell-timestamp="props">
            <q-td :props="props">
              {{ formatDateTime(props.row.timestamp) }}
            </q-td>
          </template>

          <template v-slot:body-cell-status="props">
            <q-td :props="props">
              <q-badge :color="props.row.status === 'success' ? 'positive' : 'negative'">
                {{ props.row.status }}
              </q-badge>
            </q-td>
          </template>

          <template v-slot:body-cell-actions="props">
            <q-td :props="props">
              <q-btn
                v-if="props.row.status === 'success'"
                color="primary"
                icon="visibility"
                label="View"
                @click="viewBackup(props.row)"
                class="q-mr-sm"
              />
              <q-btn
                v-if="props.row.status === 'success'"
                color="primary"
                icon="download"
                label="Download"
                @click="downloadBackup(props.row)"
              />
            </q-td>
          </template>
        </q-table>
      </q-card-section>
    </q-card>

    <q-dialog v-model="showViewDialog" maximized>
      <q-card>
        <q-card-section class="row items-center q-pb-none">
          <div class="text-h6">View Backup</div>
          <q-space />
          <q-btn icon="close" flat round dense @click="showViewDialog = false" />
        </q-card-section>
        
        <q-separator />
        
        <q-card-section class="q-pt-md">
          <div class="text-subtitle2 q-mb-md">
            <strong>Backup ID:</strong> {{ viewingBackupId }}<br>
            <strong>Date:</strong> {{ viewingBackupDate }}
          </div>
          <div class="backup-content q-pa-md rounded-borders">
            {{ viewingBackupContent }}
          </div>
        </q-card-section>
      </q-card>
    </q-dialog>
  </q-page>
</template>

<script setup>
import { ref, onMounted, computed } from 'vue'
import { useRouter, useRoute } from 'vue-router'
import { useQuasar } from 'quasar'
import api from '../services/api'

const router = useRouter()
const route = useRoute()
const $q = useQuasar()

// State
const deviceId = computed(() => parseInt(route.params.id, 10))
const deviceName = ref('')
const backups = ref([])
const loadingBackups = ref(false)
const selectedA = ref(null)
const selectedB = ref(null)
const comparePending = ref(false)

// View dialog state
const showViewDialog = ref(false)
const viewingBackupId = ref('')
const viewingBackupDate = ref('')
const viewingBackupContent = ref('')

// Pagination settings
const pagination = ref({
  page: 1,
  rowsPerPage: 20
})

// Table columns
const columns = [
  { name: 'select-a', label: 'A', field: 'id', align: 'center', style: 'width: 50px' },
  { name: 'select-b', label: 'B', field: 'id', align: 'center', style: 'width: 50px' },
  { name: 'timestamp', label: 'Date/Time', field: 'timestamp', align: 'left', sortable: true },
  { name: 'storage_backend', label: 'Backend', field: 'storage_backend', align: 'left' },
  { name: 'status', label: 'Status', field: 'status', align: 'center' },
  { name: 'actions', label: 'Actions', field: 'id', align: 'right' }
]

// Import timezone utilities
import { formatDateTime as formatDateTimeLocal, utcToLocal } from '../utils/timezone'

// Utility functions
function formatDateTime(isoString) {
  return formatDateTimeLocal(isoString)
}

function formatDateTimeForFilename(isoString) {
  const date = utcToLocal(isoString)
  const year = date.getFullYear()
  const month = String(date.getMonth() + 1).padStart(2, '0')
  const day = String(date.getDate()).padStart(2, '0')
  const hours = String(date.getHours()).padStart(2, '0')
  const minutes = String(date.getMinutes()).padStart(2, '0')
  const seconds = String(date.getSeconds()).padStart(2, '0')
  return `${year}${month}${day}-${hours}${minutes}${seconds}`
}

// Load device name
async function loadDeviceName() {
  try {
    const response = await api.get(`/devices/${deviceId.value}/`)
    deviceName.value = response.data.name || 'Device'
  } catch (error) {
    $q.notify({ type: 'negative', message: 'Failed to fetch device details' })
    deviceName.value = 'Device'
  }
}

// Load backups
async function loadBackups() {
  loadingBackups.value = true
  try {
    const response = await api.get(`/stored-backups/?device=${deviceId.value}`)
    backups.value = (response.data || []).sort((a, b) => 
      utcToLocal(b.timestamp) - utcToLocal(a.timestamp)
    )
  } catch (error) {
    $q.notify({ type: 'negative', message: 'Failed to fetch backups' })
    backups.value = []
  } finally {
    loadingBackups.value = false
  }
}

// View backup content in modal
async function viewBackup(backup) {
  if (backup.status !== 'success') {
    $q.notify({ type: 'negative', message: 'Cannot view unsuccessful backup' })
    return
  }

  try {
    showViewDialog.value = true
    viewingBackupId.value = backup.id
    viewingBackupDate.value = formatDateTime(backup.timestamp)
    viewingBackupContent.value = 'Loading...'

    const response = await api.get(`/stored-backups/${backup.id}/download/`, {
      responseType: 'text'
    })
    viewingBackupContent.value = response.data || '(empty backup)'
  } catch (error) {
    viewingBackupContent.value = `Error loading backup: ${error.response?.data?.error || error.message}`
    $q.notify({ type: 'negative', message: 'Failed to load backup content' })
  }
}

// Download backup
async function downloadBackup(backup) {
  if (backup.status !== 'success') {
    $q.notify({ type: 'negative', message: 'Cannot download unsuccessful backup' })
    return
  }

  try {
    const response = await api.get(`/stored-backups/${backup.id}/download/`, {
      responseType: 'text'
    })
    const content = response.data

    // Construct filename: devicename_backupid_YYYYMMDD-HHMMSS.txt
    const dateTime = formatDateTimeForFilename(backup.timestamp)
    const filename = `${deviceName.value}_${backup.id}_${dateTime}.txt`

    // Trigger download
    const element = document.createElement('a')
    element.setAttribute('href', 'data:text/plain;charset=utf-8,' + encodeURIComponent(content))
    element.setAttribute('download', filename)
    element.style.display = 'none'
    document.body.appendChild(element)
    element.click()
    document.body.removeChild(element)

    $q.notify({ type: 'positive', message: 'Backup downloaded successfully' })
  } catch (error) {
    $q.notify({ type: 'negative', message: 'Failed to download backup' })
  }
}

// Navigate to compare page
function navigateToCompare() {
  if (!selectedA.value || !selectedB.value) {
    $q.notify({ type: 'warning', message: 'Please select both backups to compare' })
    return
  }

  comparePending.value = true
  router.push({
    path: `/devices/${deviceId.value}/backups/compare`,
    query: {
      backup_a: selectedA.value,
      backup_b: selectedB.value
    }
  }).finally(() => {
    comparePending.value = false
  })
}

// Lifecycle
onMounted(() => {
  loadDeviceName()
  loadBackups()
})
</script>

<style scoped>
.backup-table {
  /* Ensure table rows are properly spaced */
}

.backup-content {
  overflow: auto;
  font-family: monospace;
  white-space: pre-wrap;
  word-break: break-word;
  font-size: 12px;
  line-height: 1.5;
  background: #1e1e1e;
  color: #e0e0e0;
  border: 1px solid #2d2d2d;
}
</style>
