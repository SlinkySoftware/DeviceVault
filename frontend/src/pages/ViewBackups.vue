<template>
  <q-page class="q-pa-md">
    <q-card>
      <q-card-section>
        <div class="row items-center">
          <div class="col">
            <div class="text-h5">Backups for {{ deviceName }}</div>
            <div class="text-caption text-grey">View and compare device backup configurations</div>
          </div>
          <div class="col-auto">
            <q-btn
              color="primary"
              label="Compare Selected"
              icon="compare_arrows"
              :disabled="!canCompare || comparePending"
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
                v-if="props.row.status === 'success' && props.row.is_text"
                v-model="selectedA"
                :val="props.row.id"
                color="primary"
              />
            </q-td>
          </template>

          <template v-slot:body-cell-select-b="props">
            <q-td :props="props">
              <q-radio
                v-if="props.row.status === 'success' && props.row.is_text"
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
                v-if="props.row.status === 'success' && props.row.is_text"
                color="primary"
                icon="visibility"
                label="View"
                @click="viewBackup(props.row)"
                size="sm"
                class="q-mr-xs"
              />
              <q-btn
                v-if="props.row.status === 'success'"
                color="primary"
                :icon="props.row.is_text ? 'download' : 'cloud_download'"
                :label="props.row.is_text ? 'Download' : 'Download (Binary)'"
                @click="downloadBackup(props.row)"
                size="sm"
                class="q-mr-xs"
              />
              <q-btn
                color="info"
                icon="description"
                label="View Logs"
                @click="viewLogs(props.row)"
                size="sm"
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

    <!-- Backup Log Viewer Dialog -->
    <BackupLogViewer
      v-model="showLogDialog"
      :backup-id="viewingLogBackupId"
      :backup-info="viewingLogBackupInfo"
    />
  </q-page>
</template>

<script setup>
import { ref, onMounted, computed } from 'vue'
import { useRouter, useRoute } from 'vue-router'
import { useQuasar } from 'quasar'
import api from '../services/api'
import BackupLogViewer from '../components/BackupLogViewer.vue'

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

// Computed: can only compare if both selections are text backups
const canCompare = computed(() => {
  if (!selectedA.value || !selectedB.value) return false
  const backupA = backups.value.find(b => b.id === selectedA.value)
  const backupB = backups.value.find(b => b.id === selectedB.value)
  return backupA && backupB && backupA.is_text && backupB.is_text
})

// View dialog state
const showViewDialog = ref(false)
const viewingBackupId = ref('')
const viewingBackupDate = ref('')
const viewingBackupContent = ref('')

// Log dialog state
const showLogDialog = ref(false)
const viewingLogBackupId = ref(null)
const viewingLogBackupInfo = ref(null)

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
  { name: 'is_text', label: 'Type', field: 'is_text', align: 'center', format: val => val ? 'Text' : 'Binary' },
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
    // Determine response type based on backup type
    const responseType = backup.is_text ? 'text' : 'blob'
    const response = await api.get(`/stored-backups/${backup.id}/download/`, {
      responseType: responseType
    })

    // Construct filename
    const dateTime = formatDateTimeForFilename(backup.timestamp)
    
    if (backup.is_text) {
      // Text backup: download as .txt
      const content = response.data
      const filename = `${deviceName.value}_${backup.id}_${dateTime}.txt`

      // Trigger download
      const element = document.createElement('a')
      element.setAttribute('href', 'data:text/plain;charset=utf-8,' + encodeURIComponent(content))
      element.setAttribute('download', filename)
      element.style.display = 'none'
      document.body.appendChild(element)
      element.click()
      document.body.removeChild(element)
    } else {
      // Binary backup: download as .bin
      const filename = `${deviceName.value}_${backup.id}_${dateTime}.bin`
      
      // Create blob URL for download
      const url = window.URL.createObjectURL(response.data)
      const link = document.createElement('a')
      link.href = url
      link.download = filename
      link.style.display = 'none'
      document.body.appendChild(link)
      link.click()
      document.body.removeChild(link)
      window.URL.revokeObjectURL(url)
    }

    $q.notify({ type: 'positive', message: 'Backup downloaded successfully' })
  } catch (error) {
    $q.notify({ type: 'negative', message: 'Failed to download backup' })
  }
}

// View logs
function viewLogs(backup) {
  viewingLogBackupId.value = backup.id
  viewingLogBackupInfo.value = {
    deviceName: deviceName.value,
    timestamp: formatDateTime(backup.timestamp),
    status: backup.status
  }
  showLogDialog.value = true
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
