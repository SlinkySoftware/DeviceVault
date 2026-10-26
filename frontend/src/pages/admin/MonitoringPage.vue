<!-- SPDX-License-Identifier: GPL-3.0-or-later -->
<template>
  <PageCard title="Monitoring" caption="Backup health for Zabbix and Prometheus, read from /api/monitoring/ with an API token">
    <template #actions>
      <q-btn color="primary" icon="smart_toy" label="Service Accounts" :to="{ name: 'service-accounts' }" />
    </template>

    <div class="text-h6">Set up</div>
    <ol class="q-mt-sm">
      <li>
        Create a <router-link :to="{ name: 'service-accounts' }">service account</router-link> (for example
        <code>zabbix</code>) in a user group with <strong>view</strong> on the device groups it should report on.
      </li>
      <li>
        Give it a token with the <strong>Monitoring</strong> scope, and <strong>Platform health</strong> for workers,
        the scheduler, storage targets and receivers. Limit it to your monitoring servers' networks.
      </li>
      <li>
        Send the token as <code>Authorization: Bearer &lt;token&gt;</code>. Zabbix proxies in device zones poll a
        receiver's monitoring relay for per-device status instead of this server.
      </li>
    </ol>

    <div class="text-h6 q-mt-md">Endpoints</div>
    <q-markup-table flat dense class="q-mt-sm">
      <thead>
        <tr>
          <th class="text-left">URL</th>
          <th class="text-left">Returns</th>
        </tr>
      </thead>
      <tbody>
        <tr v-for="endpoint in endpoints" :key="endpoint.path">
          <td><code>{{ origin }}/api/monitoring/{{ endpoint.path }}</code></td>
          <td>{{ endpoint.returns }}</td>
        </tr>
      </tbody>
    </q-markup-table>

    <div class="row items-center q-mt-lg">
      <div class="text-h6 col">Current figures</div>
      <q-btn flat dense icon="refresh" label="Refresh" :loading="loading" @click="load" />
    </div>
    <div class="text-caption text-grey q-mb-sm">What the summary endpoint answers for you, cached for a minute</div>
    <div v-if="figures" class="row q-col-gutter-md q-mb-md">
      <div v-for="tile in tiles" :key="tile.key" class="col-6 col-sm-4 col-md-3">
        <q-card flat bordered>
          <q-card-section>
            <div class="text-caption text-grey">{{ tile.label }}</div>
            <div class="text-h6">{{ tile.format(figures[tile.key] ?? null) }}</div>
          </q-card-section>
        </q-card>
      </div>
    </div>
    <q-input v-model="filter" dense outlined clearable debounce="200" label="Filter fields" style="max-width: 320px" />
    <q-table
      flat
      dense
      :rows="rows"
      :columns="columns"
      :filter="filter"
      row-key="key"
      :loading="loading"
      :pagination="{ rowsPerPage: 25 }"
      class="q-mt-sm"
    />
  </PageCard>
</template>

<script setup lang="ts">
import type { QTableColumn } from 'quasar'
import { computed, onMounted, ref } from 'vue'

import { monitoringApi } from '@/api/endpoints'
import type { MonitoringFigures } from '@/api/types'
import PageCard from '@/components/PageCard.vue'
import { useNotify } from '@/composables/useNotify'
import { formatAge, formatPercent } from '@/utils/monitoring'

const notify = useNotify()
const origin = window.location.origin
const figures = ref<MonitoringFigures | null>(null)
const loading = ref(false)
const filter = ref('')

const endpoints = [
  { path: 'summary/', returns: 'Estate outcomes, timing, freshness, change, volume and push (platform health with that scope)' },
  { path: 'device-groups/', returns: 'The same per device group, for Zabbix low-level discovery' },
  { path: 'device/?ip=<address>', returns: "One device's backup status, from a service account's published snapshot" },
  { path: 'workers/', returns: 'Workers: status, heartbeat age, assignment (platform health scope)' },
  { path: 'storage-targets/', returns: 'Storage targets: workers online, last stored, failures, size (platform scope)' },
  { path: 'receivers/', returns: 'Receivers: pushes accepted and refused, last push (platform scope)' },
  { path: 'metrics', returns: 'Prometheus text format: the figures above, with no per-device series' },
]

const count = (value: number | string | null) => (value === null ? '–' : String(value))
const tiles = [
  { key: 'success_ratio_24h', label: 'Success ratio (24h)', format: formatPercent },
  { key: 'finished_24h', label: 'Backups finished (24h)', format: count },
  { key: 'devices_overdue', label: 'Devices overdue', format: count },
  { key: 'devices_never', label: 'Never backed up', format: count },
  { key: 'devices_failing_3', label: 'Failing 3+ times in a row', format: count },
  { key: 'oldest_success_age', label: 'Oldest last success', format: formatAge },
  { key: 'duration_total_p95', label: 'Duration p95 (24h)', format: formatAge },
  { key: 'push_refused_24h', label: 'Pushes refused (24h)', format: count },
]

const rows = computed(() =>
  Object.entries(figures.value ?? {})
    .map(([key, value]) => ({ key, value: value === null ? 'null' : String(value) }))
    .sort((a, b) => a.key.localeCompare(b.key)),
)
const columns: QTableColumn<{ key: string; value: string }>[] = [
  { name: 'key', label: 'Field', field: 'key', align: 'left', sortable: true },
  { name: 'value', label: 'Value', field: 'value', align: 'left' },
]

async function load(): Promise<void> {
  loading.value = true
  try {
    figures.value = await monitoringApi.summary()
  } catch (error) {
    notify.error(error, 'Failed to load the monitoring figures')
  } finally {
    loading.value = false
  }
}

onMounted(load)
</script>
