<!-- SPDX-License-Identifier: GPL-3.0-or-later -->
<template>
  <q-dialog v-model="open" @before-show="load">
    <q-card class="log-card column no-wrap">
      <q-card-section class="row items-center q-pb-none">
        <div class="text-h6">Backup Logs</div>
        <q-space />
        <q-btn v-close-popup icon="close" flat round dense aria-label="Close" />
      </q-card-section>

      <q-card-section v-if="info" class="text-caption text-grey-7">
        <div>
          Device: <strong>{{ info.deviceName }}</strong>
        </div>
        <div>
          Backup time: <strong>{{ info.timestamp }}</strong>
        </div>
        <div>
          Status: <strong>{{ info.status }}</strong>
        </div>
      </q-card-section>
      <q-separator />

      <q-card-section class="col scroll">
        <div v-if="loading" class="text-center q-pa-md">
          <q-spinner color="primary" size="3em" />
        </div>
        <div v-else-if="error" class="text-center text-negative q-pa-md">
          <q-icon name="error_outline" size="3em" />
          <div class="q-mt-sm">{{ error }}</div>
        </div>
        <div v-else-if="logs.length === 0" class="text-center text-grey-7 q-pa-md">No log entries found</div>
        <q-list v-else bordered separator class="rounded-borders">
          <q-item v-for="(entry, index) in logs" :key="index">
            <q-item-section side top>
              <q-badge :color="severityColor(entry.severity)" :label="entry.severity" />
            </q-item-section>
            <q-item-section>
              <q-item-label class="log-message">{{ entry.message }}</q-item-label>
              <q-item-label caption>{{ [entry.source, formatDateTime(entry.timestamp)].filter(Boolean).join(' · ') }}</q-item-label>
            </q-item-section>
          </q-item>
        </q-list>
      </q-card-section>
    </q-card>
  </q-dialog>
</template>

<script setup lang="ts">
import { ref } from 'vue'

import { apiErrorMessage } from '@/api/client'
import { backupJobsApi } from '@/api/endpoints'
import type { LogEntry } from '@/api/types'
import { formatDateTime } from '@/utils/datetime'

import type { BackupLogInfo } from './types'

const props = defineProps<{ backupId: string | null; info?: BackupLogInfo | null }>()
const open = defineModel<boolean>({ required: true })

const logs = ref<LogEntry[]>([])
const loading = ref(false)
const error = ref('')

async function load(): Promise<void> {
  logs.value = []
  error.value = ''
  if (props.backupId === null) {
    error.value = 'No backup selected'
    return
  }
  loading.value = true
  try {
    logs.value = await backupJobsApi.logs(props.backupId)
  } catch (exc) {
    error.value = apiErrorMessage(exc, 'Failed to load backup logs')
  } finally {
    loading.value = false
  }
}

function severityColor(severity: string): string {
  switch (severity.toUpperCase()) {
    case 'ERROR':
      return 'negative'
    case 'WARN':
    case 'WARNING':
      return 'warning'
    case 'DEBUG':
      return 'info'
    default:
      return 'grey-7'
  }
}
</script>

<style scoped>
.log-card {
  width: 80vw;
  max-width: 1100px;
  height: 80vh;
}

.log-message {
  white-space: pre-wrap;
  word-break: break-word;
}
</style>
