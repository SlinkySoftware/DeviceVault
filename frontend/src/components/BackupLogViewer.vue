<template>
  <q-dialog v-model="showing" @hide="onHide">
    <q-card style="width: 80vw; max-width: 90vw; height: 80vh; max-height: 90vh; display: flex; flex-direction: column;">
      <q-card-section class="row items-center q-pb-none" style="flex-shrink: 0;">
        <div class="text-h6">Backup Logs</div>
        <q-space />
        <q-btn icon="close" flat round dense v-close-popup />
      </q-card-section>

      <q-card-section style="flex-shrink: 0;">
        <div v-if="backupInfo" class="q-mb-md">
          <div class="text-caption text-grey-7">Device: <span class="text-weight-bold">{{ backupInfo.deviceName }}</span></div>
          <div class="text-caption text-grey-7">Backup Time: <span class="text-weight-bold">{{ backupInfo.timestamp }}</span></div>
          <div class="text-caption text-grey-7">Status: <span class="text-weight-bold">{{ backupInfo.status }}</span></div>
        </div>

        <q-separator class="q-mb-md" />
      </q-card-section>

      <q-card-section style="flex: 1; overflow-y: auto; padding-top: 0;">
        <div v-if="loading" class="text-center q-pa-md">
          <q-spinner color="primary" size="3em" />
          <div class="q-mt-sm text-grey-7">Loading logs...</div>
        </div>

        <div v-else-if="error" class="text-center q-pa-md">
          <q-icon name="error_outline" color="negative" size="3em" />
          <div class="q-mt-sm text-negative">{{ error }}</div>
        </div>

        <div v-else-if="!logs || logs.length === 0" class="text-center q-pa-md text-grey-7">
          No log entries found
        </div>

        <q-list v-else bordered separator class="rounded-borders">
          <q-item v-for="(entry, index) in logs" :key="index" class="log-entry">
            <q-item-section side top>
              <q-badge :color="getSeverityColor(entry.severity)" :label="entry.severity" />
            </q-item-section>
            <q-item-section>
              <q-item-label class="text-weight-medium">{{ entry.message }}</q-item-label>
              <q-item-label caption>
                <span class="text-grey-7">{{ entry.source }}</span>
                <span class="q-mx-xs">•</span>
                <span class="text-grey-7">{{ formatTimestamp(entry.timestamp) }}</span>
              </q-item-label>
            </q-item-section>
          </q-item>
        </q-list>
      </q-card-section>

      <q-card-actions align="right" style="flex-shrink: 0;">
        <q-btn flat label="Close" color="primary" v-close-popup />
      </q-card-actions>
    </q-card>
  </q-dialog>
</template>

<script>
import { ref, watch } from 'vue'
import { formatDateTime } from '../utils/timezone'
import api from '../services/api'

export default {
  name: 'BackupLogViewer',
  props: {
    modelValue: {
      type: Boolean,
      default: false
    },
    backupId: {
      type: Number,
      default: null
    },
    backupInfo: {
      type: Object,
      default: null
    }
  },
  emits: ['update:modelValue'],
  setup(props, { emit }) {
    const showing = ref(props.modelValue)
    const loading = ref(false)
    const error = ref(null)
    const logs = ref([])

    watch(() => props.modelValue, (val) => {
      showing.value = val
      if (val && props.backupId) {
        loadLogs()
      }
    })

    watch(showing, (val) => {
      emit('update:modelValue', val)
    })

    const loadLogs = async () => {
      if (!props.backupId) {
        error.value = 'No backup ID provided'
        return
      }

      loading.value = true
      error.value = null
      logs.value = []

      try {
        const response = await api.get(`/stored-backups/${props.backupId}/logs/`)
        logs.value = response.data.logs || []
      } catch (err) {
        console.error('Error loading backup logs:', err)
        error.value = err.response?.data?.error || 'Failed to load backup logs'
      } finally {
        loading.value = false
      }
    }

    const getSeverityColor = (severity) => {
      const severityUpper = (severity || 'INFO').toUpperCase()
      switch (severityUpper) {
        case 'ERROR':
          return 'negative'
        case 'WARN':
        case 'WARNING':
          return 'warning'
        case 'DEBUG':
          return 'info'
        case 'INFO':
        default:
          return 'grey-7'
      }
    }

    const formatTimestamp = (timestamp) => {
      if (!timestamp) return ''
      try {
        return formatDateTime(timestamp)
      } catch (e) {
        return timestamp
      }
    }

    const onHide = () => {
      logs.value = []
      error.value = null
    }

    return {
      showing,
      loading,
      error,
      logs,
      getSeverityColor,
      formatTimestamp,
      onHide
    }
  }
}
</script>

<style scoped>
.log-entry {
  padding: 12px 16px;
}

.log-entry:hover {
  background-color: rgba(0, 0, 0, 0.03);
}

body.body--dark .log-entry:hover {
  background-color: rgba(255, 255, 255, 0.05);
}
</style>
