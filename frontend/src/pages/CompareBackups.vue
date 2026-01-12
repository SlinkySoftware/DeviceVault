<template>
  <q-page class="q-pa-md">
    <q-card>
      <q-card-section>
        <div class="row items-center">
          <div class="col">
            <div class="text-h4">Compare Backups</div>
            <div class="text-caption text-grey">Side-by-side comparison of device configurations</div>
          </div>
          <div class="col-auto">
            <q-btn
              color="primary"
              label="Back to Backups"
              icon="arrow_back"
              @click="goBack"
            />
          </div>
        </div>
      </q-card-section>
      
      <q-separator />
      
      <q-card-section v-if="loadingBackups" class="text-center q-py-lg">
        <q-spinner color="primary" size="50px" />
        <div class="text-grey q-mt-md">Loading backups...</div>
      </q-card-section>

      <q-card-section v-else-if="backupA && backupB">
        <div class="row q-col-gutter-md">
          <div class="col-12 col-md-6">
            <div class="bg-blue-1 q-pa-md rounded-borders q-mb-md">
              <div class="text-subtitle2 text-weight-bold">Backup A</div>
              <div class="text-caption">{{ formatDateTime(backupA.timestamp) }}</div>
            </div>
            <div class="bg-grey-2 q-pa-md rounded-borders" style="overflow: auto; max-height: 65vh; font-family: monospace; white-space: pre-wrap; word-break: break-word; font-size: 11px; line-height: 1.4;">
              {{ contentA }}
            </div>
          </div>
          <div class="col-12 col-md-6">
            <div class="bg-green-1 q-pa-md rounded-borders q-mb-md">
              <div class="text-subtitle2 text-weight-bold">Backup B</div>
              <div class="text-caption">{{ formatDateTime(backupB.timestamp) }}</div>
            </div>
            <div class="bg-grey-2 q-pa-md rounded-borders" style="overflow: auto; max-height: 65vh; font-family: monospace; white-space: pre-wrap; word-break: break-word; font-size: 11px; line-height: 1.4;">
              {{ contentB }}
            </div>
          </div>
        </div>
      </q-card-section>

      <q-card-section v-else class="text-center q-py-lg">
        <div class="text-negative">Failed to load backups for comparison</div>
      </q-card-section>
    </q-card>
  </q-page>
</template>

<script setup>
import { ref, onMounted } from 'vue'
import { useRouter, useRoute } from 'vue-router'
import { useQuasar } from 'quasar'
import api from '../services/api'

const router = useRouter()
const route = useRoute()
const $q = useQuasar()

// State
const backupA = ref(null)
const backupB = ref(null)
const contentA = ref('')
const contentB = ref('')
const loadingBackups = ref(false)

// Utility
function formatDateTime(isoString) {
  const date = new Date(isoString)
  return date.toLocaleString()
}

function goBack() {
  router.back()
}

// Load backup details and content
async function loadBackup(backupId) {
  try {
    const response = await api.get(`/stored-backups/${backupId}/`)
    return response.data
  } catch (error) {
    $q.notify({ type: 'negative', message: `Failed to fetch backup ${backupId}` })
    return null
  }
}

// Load backup content
async function loadBackupContent(backupId) {
  try {
    const response = await api.get(`/stored-backups/${backupId}/download/`, {
      responseType: 'text'
    })
    return response.data || '(empty backup)'
  } catch (error) {
    return `Error loading backup: ${error.response?.data?.error || error.message}`
  }
}

// Load both backups
async function loadBackups() {
  loadingBackups.value = true
  try {
    const backupAId = route.query.backup_a
    const backupBId = route.query.backup_b

    if (!backupAId || !backupBId) {
      $q.notify({ type: 'negative', message: 'Invalid backup IDs' })
      return
    }

    // Load backup metadata and content in parallel
    const [metaA, metaB, contentAData, contentBData] = await Promise.all([
      loadBackup(backupAId),
      loadBackup(backupBId),
      loadBackupContent(backupAId),
      loadBackupContent(backupBId)
    ])

    if (metaA) backupA.value = metaA
    if (metaB) backupB.value = metaB
    contentA.value = contentAData
    contentB.value = contentBData
  } finally {
    loadingBackups.value = false
  }
}

// Lifecycle
onMounted(() => {
  loadBackups()
})
</script>

<style scoped>
/* Comparison layout styling */
</style>
