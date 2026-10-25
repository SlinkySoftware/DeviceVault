<!-- SPDX-License-Identifier: GPL-3.0-or-later -->
<template>
  <PageCard :title="`Backups for ${deviceName}`" caption="Select an A and a B backup to compare them">
    <template #actions>
      <q-btn flat icon="arrow_back" label="Devices" :to="{ name: 'devices' }" />
      <q-btn
        v-if="mayRead"
        color="primary"
        icon="compare_arrows"
        label="Compare Selected"
        :disable="!canCompare"
        :to="compareTarget"
      />
    </template>

    <q-table
      v-model:pagination="pagination"
      flat
      :rows="jobs"
      :columns="columns"
      row-key="id"
      :loading="loading"
      :rows-per-page-options="[20, 50, 100]"
      no-data-label="No backups found for this device"
      class="admin-table"
      @request="onRequest"
    >
      <template #body-cell-select-a="props">
        <q-td :props="props">
          <q-radio v-if="mayRead && comparable(props.row)" v-model="selectedA" :val="props.row.id" aria-label="Compare as A" />
        </q-td>
      </template>
      <template #body-cell-select-b="props">
        <q-td :props="props">
          <q-radio v-if="mayRead && comparable(props.row)" v-model="selectedB" :val="props.row.id" aria-label="Compare as B" />
        </q-td>
      </template>
      <template #body-cell-state="props">
        <q-td :props="props">
          <StatusLabel :status="props.row.state" />
          <q-tooltip v-if="props.row.error">{{ props.row.error }}</q-tooltip>
          <q-badge v-if="props.row.pruned" color="grey" class="q-ml-xs">
            Deleted
            <q-tooltip>Deleted by its retention policy{{ props.row.pruned_at ? ` on ${formatDateTime(props.row.pruned_at)}` : '' }}</q-tooltip>
          </q-badge>
          <q-icon v-if="props.row.pinned" name="push_pin" color="primary" size="xs" class="q-ml-xs">
            <q-tooltip>Pinned: kept whatever the retention policy says</q-tooltip>
          </q-icon>
        </q-td>
      </template>
      <template #body-cell-trigger="props">
        <q-td :props="props">
          {{ capitalise(props.row.trigger) }}
          <div v-if="props.row.source_filename" class="text-caption text-grey">{{ props.row.source_filename }}</div>
        </q-td>
      </template>
      <template #body-cell-encrypted="props">
        <q-td :props="props">
          <q-icon
            v-if="available(props.row)"
            :name="props.row.encrypted ? 'lock' : 'lock_open'"
            :color="props.row.encrypted ? 'primary' : 'grey-5'"
            size="sm"
          >
            <q-tooltip>{{ props.row.encrypted ? 'Encrypted at rest' : 'Not encrypted' }}</q-tooltip>
          </q-icon>
        </q-td>
      </template>
      <template #body-cell-actions="props">
        <q-td :props="props" class="no-wrap">
          <q-btn v-if="mayRead && comparable(props.row)" dense round flat color="primary" icon="visibility" aria-label="View" @click="view(props.row)">
            <q-tooltip>View</q-tooltip>
          </q-btn>
          <q-btn
            v-if="mayDownload && available(props.row)"
            dense
            round
            flat
            color="primary"
            icon="download"
            aria-label="Download"
            :loading="downloading.has(props.row.id)"
            @click="download(props.row)"
          >
            <q-tooltip>{{ props.row.is_binary ? 'Download (binary)' : 'Download' }}</q-tooltip>
          </q-btn>
          <q-btn dense round flat color="info" icon="description" aria-label="Logs" @click="openLogs(props.row)">
            <q-tooltip>Logs</q-tooltip>
          </q-btn>
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
import type { QTableColumn, QTableProps } from 'quasar'
import { computed, onMounted, reactive, ref } from 'vue'
import { useRoute, type RouteLocationRaw } from 'vue-router'

import { backupJobsApi, devicesApi } from '@/api/endpoints'
import type { BackupJob, GrantFlag } from '@/api/types'
import BackupLogViewer from '@/components/BackupLogViewer.vue'
import PageCard from '@/components/PageCard.vue'
import StatusLabel from '@/components/StatusLabel.vue'
import type { BackupLogInfo } from '@/components/types'
import { useNotify } from '@/composables/useNotify'
import { usePolling } from '@/composables/usePolling'
import { filenameTimestamp, formatDateTime } from '@/utils/datetime'
import { safeFilename, saveFile } from '@/utils/download'
import { capitalise, formatBytes, formatDuration, isActiveJob, statusLabel } from '@/utils/format'

type Pagination = NonNullable<QTableProps['pagination']>

const route = useRoute()
const notify = useNotify()
const deviceId = computed(() => Number(route.params.id))

const deviceName = ref('device')
const jobs = ref<BackupJob[]>([])
const loading = ref(false)
const pagination = ref<Pagination>({ page: 1, rowsPerPage: 20, rowsNumber: 0 })
const selectedA = ref<string | null>(null)
const selectedB = ref<string | null>(null)
const downloading = reactive(new Set<string>())

// What the user may do with this device's backups (hidden otherwise; the API enforces it).
const permissions = ref<GrantFlag[]>([])
const mayRead = computed(() => permissions.value.includes('view_contents'))
const mayDownload = computed(() => permissions.value.includes('download'))

const columns: QTableColumn<BackupJob>[] = [
  { name: 'select-a', label: 'A', field: 'id', align: 'center', style: 'width: 48px' },
  { name: 'select-b', label: 'B', field: 'id', align: 'center', style: 'width: 48px' },
  { name: 'created_at', label: 'Requested', field: 'created_at', format: formatDateTime, align: 'left' },
  { name: 'state', label: 'Status', field: 'state', align: 'left' },
  { name: 'trigger', label: 'Trigger', field: 'trigger', format: capitalise, align: 'left' },
  { name: 'type', label: 'Type', field: 'is_binary', format: (binary: boolean) => (binary ? 'Binary' : 'Text'), align: 'center' },
  { name: 'size', label: 'Size', field: 'size_bytes', format: formatBytes, align: 'right' },
  { name: 'duration', label: 'Took', field: 'duration_ms', format: formatDuration, align: 'right' },
  { name: 'target', label: 'Stored in', field: 'storage_target_name', align: 'left' },
  { name: 'encrypted', label: 'Encrypted', field: 'encrypted', align: 'center' },
  { name: 'actions', label: 'Actions', field: 'id', align: 'right' },
]

// Stored and not deleted by retention, so its content can be read.
const available = (job: BackupJob) => job.state === 'stored' && !job.pruned
const comparable = (job: BackupJob) => available(job) && !job.is_binary
const canCompare = computed(
  () => selectedA.value !== null && selectedB.value !== null && selectedA.value !== selectedB.value,
)
const compareTarget = computed<RouteLocationRaw>(() => ({
  name: 'device-backups-compare',
  params: { id: deviceId.value },
  query: { a: selectedA.value ?? '', b: selectedB.value ?? '' },
}))

async function load(): Promise<void> {
  const { page = 1, rowsPerPage = 20 } = pagination.value
  try {
    const result = await backupJobsApi.list({ device: deviceId.value, page, page_size: rowsPerPage })
    jobs.value = result.results
    pagination.value = { ...pagination.value, rowsNumber: result.count }
  } catch (error) {
    notify.error(error, 'Failed to load backups')
  }
}

async function onRequest(request: { pagination: Pagination }): Promise<void> {
  pagination.value = { ...pagination.value, ...request.pagination }
  loading.value = true
  await load()
  loading.value = false
}

// Refresh while a backup is in progress, so its outcome appears without a reload.
const interval = computed(() => (jobs.value.some((job) => isActiveJob(job.state)) ? 5_000 : 60_000))
usePolling(load, interval)

const viewer = reactive({ open: false, loading: false, title: '', content: '' })

async function view(job: BackupJob): Promise<void> {
  Object.assign(viewer, { open: true, loading: true, title: formatDateTime(job.created_at), content: '' })
  try {
    viewer.content = (await backupJobsApi.contentText(job.id)) || '(empty backup)'
  } catch (error) {
    viewer.open = false
    notify.error(error, 'Failed to load backup content')
  } finally {
    viewer.loading = false
  }
}

async function download(job: BackupJob): Promise<void> {
  downloading.add(job.id)
  try {
    const base = `${safeFilename(deviceName.value)}_${filenameTimestamp(job.created_at)}`
    saveFile(await backupJobsApi.download(job.id), `${base}${job.is_binary ? '.bin' : '.txt'}`)
  } catch (error) {
    notify.error(error, 'Failed to download backup')
  } finally {
    downloading.delete(job.id)
  }
}

const logs = reactive<{ open: boolean; backupId: string | null; info: BackupLogInfo | null }>({
  open: false,
  backupId: null,
  info: null,
})

function openLogs(job: BackupJob): void {
  logs.backupId = job.id
  logs.info = { deviceName: deviceName.value, timestamp: formatDateTime(job.created_at), status: statusLabel(job.state) }
  logs.open = true
}

onMounted(async () => {
  try {
    const device = await devicesApi.get(deviceId.value)
    deviceName.value = device.name
    permissions.value = device.user_permissions
  } catch (error) {
    notify.error(error, 'Failed to load device')
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
