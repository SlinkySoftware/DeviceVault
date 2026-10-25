<!-- SPDX-License-Identifier: GPL-3.0-or-later -->
<template>
  <PageCard :title="`Backups for ${deviceName}`" caption="Select an A and a B backup to compare them">
    <template #actions>
      <q-btn flat icon="arrow_back" label="Devices" :to="{ name: 'devices' }" />
      <q-toggle v-model="onlyChanges" label="Only changes" @update:model-value="reload" />
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
      <template #body-cell-changes="props">
        <q-td :props="props">
          <router-link
            v-if="mayRead && props.row.changed && props.row.compared_to && comparable(props.row)"
            :to="compareWithPrevious(props.row)"
            class="change-link"
          >
            {{ changeLabel(props.row) }}
            <q-tooltip>Compare with the previous backup</q-tooltip>
          </router-link>
          <span v-else-if="changeLabel(props.row)" :class="{ 'text-grey': !props.row.changed }">{{ changeLabel(props.row) }}</span>
          <span v-else class="text-grey">
            —
            <q-tooltip v-if="props.row.summary_error">{{ props.row.summary_error }}</q-tooltip>
          </span>
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
        <q-card-section class="col column no-wrap">
          <q-inner-loading :showing="viewer.loading" />
          <q-virtual-scroll
            ref="scroller"
            v-slot="{ item, index }"
            class="col backup-content"
            :items="viewerLines"
            :virtual-scroll-item-size="18"
          >
            <div :key="index" class="content-line" :class="{ target: index + 1 === viewer.line }">
              <span class="line-number">{{ index + 1 }}</span>
              <span class="line-text">{{ item }}</span>
            </div>
          </q-virtual-scroll>
        </q-card-section>
      </q-card>
    </q-dialog>

    <BackupLogViewer v-model="logs.open" :backup-id="logs.backupId" :info="logs.info" />
  </PageCard>
</template>

<script setup lang="ts">
import type { QTableColumn, QTableProps, QVirtualScroll } from 'quasar'
import { computed, nextTick, onMounted, reactive, ref, watch } from 'vue'
import { useRoute, useRouter, type RouteLocationRaw } from 'vue-router'

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
import { capitalise, changeLabel, formatBytes, formatDuration, isActiveJob, statusLabel } from '@/utils/format'

type Pagination = NonNullable<QTableProps['pagination']>

const route = useRoute()
const router = useRouter()
const notify = useNotify()
const deviceId = computed(() => Number(route.params.id))

const deviceName = ref('device')
const jobs = ref<BackupJob[]>([])
const loading = ref(false)
const pagination = ref<Pagination>({ page: 1, rowsPerPage: 20, rowsNumber: 0 })
const selectedA = ref<string | null>(null)
const selectedB = ref<string | null>(null)
const downloading = reactive(new Set<string>())
const onlyChanges = ref(false)

// What the user may do with this device's backups (hidden otherwise; the API enforces it).
const permissions = ref<GrantFlag[]>([])
const mayRead = computed(() => permissions.value.includes('view_contents'))
const mayDownload = computed(() => permissions.value.includes('download'))

const columns: QTableColumn<BackupJob>[] = [
  { name: 'select-a', label: 'A', field: 'id', align: 'center', style: 'width: 48px' },
  { name: 'select-b', label: 'B', field: 'id', align: 'center', style: 'width: 48px' },
  { name: 'created_at', label: 'Requested', field: 'created_at', format: formatDateTime, align: 'left' },
  { name: 'state', label: 'Status', field: 'state', align: 'left' },
  { name: 'changes', label: 'Changes', field: 'changed', align: 'left' },
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
const compareWithPrevious = (job: BackupJob): RouteLocationRaw => ({
  name: 'device-backups-compare',
  params: { id: deviceId.value },
  query: { a: job.compared_to ?? '', b: job.id },
})
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
    const result = await backupJobsApi.list({
      device: deviceId.value,
      page,
      page_size: rowsPerPage,
      ...(onlyChanges.value ? { changed: true } : {}),
    })
    jobs.value = result.results
    pagination.value = { ...pagination.value, rowsNumber: result.count }
  } catch (error) {
    notify.error(error, 'Failed to load backups')
  }
}

async function reload(): Promise<void> {
  pagination.value = { ...pagination.value, page: 1 }
  loading.value = true
  await load()
  loading.value = false
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

const viewer = reactive<{ open: boolean; loading: boolean; title: string; content: string; line: number | null }>({
  open: false,
  loading: false,
  title: '',
  content: '',
  line: null,
})
const viewerLines = computed(() => viewer.content.split('\n'))
const scroller = ref<QVirtualScroll | null>(null)

/** Show a backup's content; `line` (1-based) is highlighted and scrolled to. */
async function view(job: BackupJob, line: number | null = null): Promise<void> {
  Object.assign(viewer, { open: true, loading: true, title: formatDateTime(job.created_at), content: '', line })
  try {
    viewer.content = (await backupJobsApi.contentText(job.id)) || '(empty backup)'
  } catch (error) {
    viewer.open = false
    notify.error(error, 'Failed to load backup content')
  } finally {
    viewer.loading = false
  }
  if (viewer.open && line) {
    await nextTick()
    scroller.value?.scrollTo(line - 1, 'center-force')
  }
}

/** Config search links here with ?view=<job>&line=<n>. */
async function viewFromRoute(): Promise<void> {
  const { view: jobId, line } = route.query
  if (typeof jobId !== 'string' || !jobId) return
  try {
    await view(await backupJobsApi.get(jobId), Number(line) || null)
  } catch (error) {
    notify.error(error, 'Failed to load backup')
  }
}

// Closing a viewer opened from a link drops the link, so a reload does not reopen it.
watch(
  () => viewer.open,
  (open) => {
    if (!open && route.query.view) void router.replace({ query: {} })
  },
)

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
  await viewFromRoute()
})
</script>

<style scoped>
.change-link {
  text-decoration: none;
  font-family: ui-monospace, SFMono-Regular, Menlo, Consolas, monospace;
}

.backup-content {
  margin: 0;
  padding: 16px 0;
  font-family: ui-monospace, SFMono-Regular, Menlo, Consolas, monospace;
  font-size: 12px;
  line-height: 1.5;
  background: #1e1e1e;
  color: #e0e0e0;
  border-radius: 4px;
}

.content-line {
  display: flex;
  padding: 0 16px 0 0;
}

.content-line.target {
  background: rgba(255, 213, 79, 0.25);
}

.line-number {
  flex: 0 0 4.5em;
  padding-right: 1em;
  text-align: right;
  color: #777;
  user-select: none;
}

.line-text {
  white-space: pre-wrap;
  word-break: break-word;
}
</style>
