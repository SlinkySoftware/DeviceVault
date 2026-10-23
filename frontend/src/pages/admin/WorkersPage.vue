<!-- SPDX-License-Identifier: GPL-3.0-or-later -->
<template>
  <PageCard title="Workers" caption="Registered collection and storage workers, their queues and liveness">
    <template #actions>
      <q-btn color="primary" icon="refresh" label="Refresh" :loading="loading" @click="load" />
    </template>

    <q-table
      flat
      :rows="registry?.workers ?? []"
      :columns="columns"
      row-key="worker_id"
      :loading="loading && !registry"
      no-data-label="No workers have registered"
      class="admin-table"
    >
      <template #body-cell-status="props">
        <q-td :props="props">
          <q-badge :color="props.row.is_online ? 'positive' : 'negative'" :label="props.row.status.toUpperCase()" />
        </q-td>
      </template>
      <template #body-cell-worker_name="props">
        <q-td :props="props">
          <div class="text-weight-medium">{{ props.row.worker_name }}</div>
          <div class="text-caption text-grey">{{ props.row.worker_id }}</div>
        </q-td>
      </template>
      <template #body-cell-queues="props">
        <q-td :props="props">
          <div class="row q-gutter-xs">
            <q-badge v-for="queue in props.row.queues" :key="queue" color="primary" outline :label="queue" />
            <span v-if="props.row.queues.length === 0" class="text-grey">—</span>
          </div>
        </q-td>
      </template>
      <template #body-cell-last_seen_at="props">
        <q-td :props="props"><TimeCell :value="props.row.last_seen_at" /></q-td>
      </template>
      <template #body-cell-last_pong_at="props">
        <q-td :props="props"><TimeCell :value="props.row.last_pong_at" /></q-td>
      </template>
    </q-table>

    <div v-if="registry" class="text-caption text-grey q-mt-sm">
      Online timeout {{ registry.online_timeout_seconds }}s · probe grace {{ registry.pong_grace_seconds }}s ·
      refreshes every 10s
    </div>
  </PageCard>
</template>

<script setup lang="ts">
import type { QTableColumn } from 'quasar'
import { ref } from 'vue'

import { workersApi } from '@/api/endpoints'
import type { WorkerRegistry, WorkerStatus } from '@/api/types'
import PageCard from '@/components/PageCard.vue'
import TimeCell from '@/components/TimeCell.vue'
import { useNotify } from '@/composables/useNotify'
import { usePolling } from '@/composables/usePolling'

const notify = useNotify()
const registry = ref<WorkerRegistry | null>(null)
const loading = ref(false)
let reportedFailure = false

const columns: QTableColumn<WorkerStatus>[] = [
  { name: 'status', label: 'Status', field: 'status', align: 'left', sortable: true },
  { name: 'worker_name', label: 'Worker', field: 'worker_name', align: 'left', sortable: true },
  { name: 'worker_type', label: 'Type', field: 'worker_type', align: 'left', sortable: true },
  { name: 'hostname', label: 'Host', field: 'hostname', align: 'left', sortable: true },
  { name: 'queues', label: 'Queues', field: 'queues', align: 'left' },
  { name: 'last_seen_at', label: 'Last Seen', field: 'last_seen_at', align: 'left', sortable: true },
  { name: 'last_pong_at', label: 'Last Probe Reply', field: 'last_pong_at', align: 'left', sortable: true },
]

async function load(): Promise<void> {
  loading.value = true
  try {
    registry.value = await workersApi.registry()
    reportedFailure = false
  } catch (error) {
    // Report once rather than every 10 seconds.
    if (!reportedFailure) notify.error(error, 'Failed to load the worker registry')
    reportedFailure = true
  } finally {
    loading.value = false
  }
}

usePolling(load, 10_000)
</script>
