<!-- SPDX-License-Identifier: GPL-3.0-or-later -->
<template>
  <PageCard title="Workers" caption="Collectors and storage workers register themselves; approve them to give them work">
    <template #actions>
      <q-btn color="primary" icon="refresh" label="Refresh" :loading="loading" @click="load" />
    </template>

    <q-banner v-if="identity" dense rounded class="q-mb-md bg-grey-2 text-black">
      <template #avatar><q-icon name="verified_user" color="primary" /></template>
      Workers pin this orchestrator's key when first approved. Its fingerprint:
      <span class="fingerprint">{{ identity.fingerprint }}</span>
    </q-banner>

    <q-banner v-if="pending.length" dense rounded class="q-mb-md bg-warning text-black">
      <template #avatar><q-icon name="pending_actions" /></template>
      {{ pending.length }} worker{{ pending.length === 1 ? '' : 's' }} waiting for approval.
    </q-banner>

    <q-table
      flat
      :rows="workers"
      :columns="columns"
      row-key="id"
      :loading="loading && workers.length === 0"
      :pagination="{ rowsPerPage: 25, sortBy: 'status' }"
      no-data-label="No workers have registered yet. Start one with only DV_BROKER_URL and DV_REDIS_URL set."
      class="admin-table"
    >
      <template #body-cell-status="props">
        <q-td :props="props">
          <q-badge :color="statusColor(props.row.status)" :label="props.row.status" />
          <div class="row items-center no-wrap q-mt-xs text-caption">
            <q-icon name="circle" size="10px" :color="props.row.is_online ? 'positive' : 'grey'" class="q-mr-xs" />
            {{ props.row.is_online ? 'online' : 'offline' }}
          </div>
        </q-td>
      </template>
      <template #body-cell-name="props">
        <q-td :props="props">
          <div class="text-weight-medium">{{ props.row.name }}</div>
          <div class="text-caption text-grey">{{ props.row.hostname }} · v{{ props.row.version || '?' }}</div>
        </q-td>
      </template>
      <template #body-cell-fingerprint="props">
        <q-td :props="props">
          <span class="fingerprint fingerprint--short">{{ props.row.fingerprint }}</span>
          <q-tooltip>{{ props.row.fingerprint }}</q-tooltip>
        </q-td>
      </template>
      <template #body-cell-assignment="props">
        <q-td :props="props">
          <div v-if="props.row.status === 'approved'">
            <div class="text-weight-medium">{{ roleLabel(props.row.role) }}</div>
            <div class="row q-gutter-xs q-mt-xs">
              <q-badge v-for="queue in props.row.assigned_queues" :key="queue" outline color="primary" :label="queue" />
              <span v-if="props.row.assigned_queues.length === 0" class="text-grey">No queues</span>
            </div>
          </div>
          <span v-else class="text-grey">—</span>
        </q-td>
      </template>
      <template #body-cell-sync="props">
        <q-td :props="props">
          <template v-if="props.row.status !== 'pending'">
            <q-badge
              :color="props.row.in_sync ? 'positive' : 'warning'"
              :label="props.row.in_sync ? `v${props.row.applied_version}` : `applying v${props.row.desired_version}`"
            />
            <div v-if="props.row.pinned_orchestrator_matches === false" class="text-caption text-negative q-mt-xs">
              <q-icon name="warning" /> pinned a different orchestrator
            </div>
          </template>
        </q-td>
      </template>
      <template #body-cell-last_seen_at="props">
        <q-td :props="props"><TimeCell :value="props.row.last_seen_at" /></q-td>
      </template>
      <template #body-cell-actions="props">
        <q-td :props="props" class="q-gutter-xs">
          <q-btn
            v-if="props.row.status !== 'approved'"
            dense
            color="positive"
            icon="check"
            label="Approve"
            @click="openAssignment(props.row)"
          />
          <template v-else>
            <q-btn dense round flat color="primary" icon="tune" aria-label="Change assignment" @click="openAssignment(props.row)">
              <q-tooltip>Change assignment</q-tooltip>
            </q-btn>
            <q-btn dense round flat color="warning" icon="block" aria-label="Revoke" @click="confirmRevoke(props.row)">
              <q-tooltip>Revoke</q-tooltip>
            </q-btn>
          </template>
          <q-btn dense round flat color="negative" icon="delete" aria-label="Forget worker" @click="confirmForget(props.row)">
            <q-tooltip>Forget this worker</q-tooltip>
          </q-btn>
        </q-td>
      </template>
    </q-table>

    <div v-if="identity" class="text-caption text-grey q-mt-sm">
      A worker is offline after {{ identity.online_timeout_seconds }}s without a heartbeat · refreshes every 10s
    </div>

    <WorkerAssignmentDialog v-model="assignmentOpen" :worker="selected" @saved="load" />
  </PageCard>
</template>

<script setup lang="ts">
import { useQuasar, type QTableColumn } from 'quasar'
import { computed, onMounted, ref } from 'vue'

import { workersApi } from '@/api/endpoints'
import type { OrchestratorIdentity, Worker, WorkerStatus } from '@/api/types'
import PageCard from '@/components/PageCard.vue'
import TimeCell from '@/components/TimeCell.vue'
import WorkerAssignmentDialog from '@/components/WorkerAssignmentDialog.vue'
import { useNotify } from '@/composables/useNotify'
import { usePolling } from '@/composables/usePolling'

const STATUS_COLORS: Record<WorkerStatus, string> = { pending: 'warning', approved: 'positive', revoked: 'grey' }
const ROLE_LABELS: Record<string, string> = { collector: 'Collector', storage: 'Storage' }
const statusColor = (status: WorkerStatus) => STATUS_COLORS[status]
const roleLabel = (role: string) => ROLE_LABELS[role] ?? 'Unassigned'
const STATUS_ORDER: Record<WorkerStatus, number> = { pending: 0, approved: 1, revoked: 2 }

const $q = useQuasar()
const notify = useNotify()
const workers = ref<Worker[]>([])
const identity = ref<OrchestratorIdentity | null>(null)
const loading = ref(false)
const pending = computed(() => workers.value.filter((w) => w.status === 'pending'))
let reportedFailure = false

const columns: QTableColumn<Worker>[] = [
  {
    name: 'status',
    label: 'Status',
    field: 'status',
    align: 'left',
    sortable: true,
    sort: (a: WorkerStatus, b: WorkerStatus) => STATUS_ORDER[a] - STATUS_ORDER[b],
  },
  { name: 'name', label: 'Worker', field: 'name', align: 'left', sortable: true },
  { name: 'fingerprint', label: 'Fingerprint', field: 'fingerprint', align: 'left' },
  { name: 'assignment', label: 'Assignment', field: 'role', align: 'left' },
  { name: 'sync', label: 'Applied', field: 'applied_version', align: 'left' },
  { name: 'last_seen_at', label: 'Last seen', field: 'last_seen_at', align: 'left', sortable: true },
  { name: 'actions', label: 'Actions', field: 'id', align: 'right' },
]

async function load(): Promise<void> {
  loading.value = true
  try {
    workers.value = await workersApi.list()
    reportedFailure = false
  } catch (error) {
    if (!reportedFailure) notify.error(error, 'Failed to load workers')
    reportedFailure = true
  } finally {
    loading.value = false
  }
}

const assignmentOpen = ref(false)
const selected = ref<Worker | null>(null)

function openAssignment(worker: Worker): void {
  selected.value = worker
  assignmentOpen.value = true
}

function confirm(title: string, message: string, label: string, color: string, action: () => Promise<void>): void {
  $q.dialog({ title, message, cancel: true, persistent: true, ok: { label, color } }).onOk(async () => {
    try {
      await action()
      await load()
    } catch (error) {
      notify.error(error, `${label} failed`)
    }
  })
}

function confirmRevoke(worker: Worker): void {
  confirm(
    'Revoke worker',
    `${worker.name} will stop consuming all queues immediately. You can approve it again later.`,
    'Revoke',
    'warning',
    async () => {
      await workersApi.revoke(worker.id)
      notify.success(`${worker.name} revoked`)
    },
  )
}

function confirmForget(worker: Worker): void {
  confirm(
    'Forget worker',
    `Remove ${worker.name}? If it is still running it registers again as pending.`,
    'Forget',
    'negative',
    async () => {
      await workersApi.forget(worker.id)
      notify.success(`${worker.name} forgotten`)
    },
  )
}

usePolling(load, 10_000)
onMounted(async () => {
  try {
    identity.value = await workersApi.orchestrator()
  } catch (error) {
    notify.error(error, 'Failed to load the orchestrator identity')
  }
})
</script>

<style scoped>
.fingerprint {
  font-family: ui-monospace, SFMono-Regular, Menlo, Consolas, monospace;
  font-size: 0.8rem;
  word-break: break-all;
}

.fingerprint--short {
  display: inline-block;
  max-width: 18ch;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
  vertical-align: bottom;
}
</style>
