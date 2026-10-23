<!-- SPDX-License-Identifier: GPL-3.0-or-later -->
<template>
  <PageCard :title="`Backups for ${deviceName}`" caption="Select an A and a B backup to compare them">
    <template #actions>
      <q-btn flat icon="arrow_back" label="Devices" :to="{ name: 'devices' }" />
      <q-btn
        color="primary"
        icon="compare_arrows"
        label="Compare Selected"
        :disable="!canCompare"
        :to="compareTarget"
      />
    </template>

    <q-table
      flat
      :rows="backups"
      :columns="columns"
      row-key="id"
      :loading="loading"
      :pagination="{ rowsPerPage: 20, sortBy: 'timestamp', descending: true }"
      :rows-per-page-options="[20, 50, 100, 0]"
      no-data-label="No backups found for this device"
      class="admin-table"
    >
      <template #body-cell-select-a="props">
        <q-td :props="props">
          <q-radio v-if="comparable(props.row)" v-model="selectedA" :val="props.row.id" :aria-label="`Compare as A`" />
        </q-td>
      </template>
      <template #body-cell-select-b="props">
        <q-td :props="props">
          <q-radio v-if="comparable(props.row)" v-model="selectedB" :val="props.row.id" :aria-label="`Compare as B`" />
        </q-td>
      </template>
      <template #body-cell-status="props">
        <q-td :props="props">
          <q-badge :color="statusColor(props.row.status)">{{ props.row.status }}</q-badge>
        </q-td>
      </template>
      <template #body-cell-encrypted="props">
        <q-td :props="props">
          <q-icon
            :name="props.row.is_encrypted ? 'lock' : 'lock_open'"
            :color="props.row.is_encrypted ? 'primary' : 'grey-5'"
            size="sm"
          >
            <q-tooltip>{{ props.row.is_encrypted ? 'Encrypted at rest' : 'Not encrypted' }}</q-tooltip>
          </q-icon>
        </q-td>
      </template>
      <template #body-cell-actions="props">
        <q-td :props="props" class="q-gutter-xs">
          <q-btn v-if="comparable(props.row)" dense size="sm" color="primary" icon="visibility" label="View" @click="view(props.row)" />
          <q-btn
            v-if="props.row.status === 'success'"
            dense
            size="sm"
            color="primary"
            icon="download"
            :label="props.row.is_text ? 'Download' : 'Download (binary)'"
            :loading="downloading.has(props.row.id)"
            @click="download(props.row)"
          />
          <q-btn dense size="sm" color="info" icon="description" label="Logs" @click="openLogs(props.row)" />
        </q-td>
      </template>
    </q-table>

    <q-dialog v-model="viewer.open" maximized>
      <q-card class="column no-wrap">
        <q-card-section class="row items-center">
          <div class="text-h6">{{ deviceName }} · {{ viewer.title }}</div>
          <q-space />
          <q-btn v-close-popup icon="close" flat round dense aria-label="Close" />
        </q-card-section>
        <q-separator />
        <q-card-section class="col scroll">
          <q-inner-loading :showing="viewer.loading" />
          <pre class="backup-content">{{ viewer.content }}</pre>
        </q-card-section>
      </q-card>
    </q-dialog>

    <BackupLogViewer v-model="logs.open" :backup-id="logs.backupId" :info="logs.info" />
  </PageCard>
</template>

<script setup lang="ts">
import type { QTableColumn } from 'quasar'
import { computed, onMounted, reactive, ref } from 'vue'
import { useRoute, type RouteLocationRaw } from 'vue-router'

import { devicesApi, storedBackupsApi } from '@/api/endpoints'
import type { Id, StoredBackup } from '@/api/types'
import BackupLogViewer from '@/components/BackupLogViewer.vue'
import PageCard from '@/components/PageCard.vue'
import type { BackupLogInfo } from '@/components/types'
import { useNotify } from '@/composables/useNotify'
import { filenameTimestamp, formatDateTime } from '@/utils/datetime'
import { safeFilename, saveFile } from '@/utils/download'
import { statusColor } from '@/utils/format'

const route = useRoute()
const notify = useNotify()
const deviceId = computed(() => Number(route.params.id))

const deviceName = ref('device')
const backups = ref<StoredBackup[]>([])
const loading = ref(false)
const selectedA = ref<Id | null>(null)
const selectedB = ref<Id | null>(null)
const downloading = reactive(new Set<Id>())

const columns: QTableColumn<StoredBackup>[] = [
  { name: 'select-a', label: 'A', field: 'id', align: 'center', style: 'width: 48px' },
  { name: 'select-b', label: 'B', field: 'id', align: 'center', style: 'width: 48px' },
  { name: 'timestamp', label: 'Date/Time', field: 'timestamp', format: formatDateTime, align: 'left', sortable: true },
  { name: 'type', label: 'Type', field: 'is_text', format: (text: boolean) => (text ? 'Text' : 'Binary'), align: 'center' },
  { name: 'storage_backend', label: 'Backend', field: 'storage_backend', align: 'left' },
  { name: 'status', label: 'Status', field: 'status', align: 'center', sortable: true },
  { name: 'encrypted', label: 'Encrypted', field: 'is_encrypted', align: 'center' },
  { name: 'actions', label: 'Actions', field: 'id', align: 'right' },
]

const comparable = (backup: StoredBackup) => backup.status === 'success' && backup.is_text
const canCompare = computed(
  () => selectedA.value !== null && selectedB.value !== null && selectedA.value !== selectedB.value,
)
const compareTarget = computed<RouteLocationRaw>(() => ({
  name: 'device-backups-compare',
  params: { id: deviceId.value },
  query: { a: String(selectedA.value), b: String(selectedB.value) },
}))

const viewer = reactive({ open: false, loading: false, title: '', content: '' })

async function view(backup: StoredBackup): Promise<void> {
  Object.assign(viewer, { open: true, loading: true, title: formatDateTime(backup.timestamp), content: '' })
  try {
    viewer.content = (await storedBackupsApi.downloadText(backup.id)) || '(empty backup)'
  } catch (error) {
    viewer.open = false
    notify.error(error, 'Failed to load backup content')
  } finally {
    viewer.loading = false
  }
}

async function download(backup: StoredBackup): Promise<void> {
  downloading.add(backup.id)
  try {
    const base = `${safeFilename(deviceName.value)}_${backup.id}_${filenameTimestamp(backup.timestamp)}`
    if (backup.is_text) {
      saveFile(await storedBackupsApi.downloadText(backup.id), `${base}.txt`)
    } else {
      saveFile(await storedBackupsApi.downloadBlob(backup.id), `${base}.bin`)
    }
  } catch (error) {
    notify.error(error, 'Failed to download backup')
  } finally {
    downloading.delete(backup.id)
  }
}

const logs = reactive<{ open: boolean; backupId: Id | null; info: BackupLogInfo | null }>({
  open: false,
  backupId: null,
  info: null,
})

function openLogs(backup: StoredBackup): void {
  logs.backupId = backup.id
  logs.info = { deviceName: deviceName.value, timestamp: formatDateTime(backup.timestamp), status: backup.status }
  logs.open = true
}

onMounted(async () => {
  loading.value = true
  try {
    const [device, list] = await Promise.all([
      devicesApi.get(deviceId.value),
      storedBackupsApi.listForDevice(deviceId.value),
    ])
    deviceName.value = device.name
    backups.value = list
  } catch (error) {
    notify.error(error, 'Failed to load backups')
  } finally {
    loading.value = false
  }
})
</script>

<style scoped>
.backup-content {
  margin: 0;
  padding: 16px;
  font-family: ui-monospace, SFMono-Regular, Menlo, Consolas, monospace;
  font-size: 12px;
  line-height: 1.5;
  white-space: pre-wrap;
  word-break: break-word;
  background: #1e1e1e;
  color: #e0e0e0;
  border-radius: 4px;
}
</style>
