<!-- SPDX-License-Identifier: GPL-3.0-or-later -->
<template>
  <PageCard title="Audit Log" caption="Sign-ins, access changes, backup content views and refused requests">
    <template #actions>
      <q-btn flat icon="refresh" label="Refresh" :loading="loading" @click="reload" />
    </template>

    <div class="row q-col-gutter-md q-mb-md">
      <div class="col-12 col-sm-6 col-md-3">
        <q-select
          v-model="filters.action"
          :options="ACTION_OPTIONS"
          emit-value
          map-options
          outlined
          dense
          clearable
          label="Action"
          @update:model-value="reload"
        />
      </div>
      <div class="col-12 col-sm-6 col-md-3">
        <q-select
          v-model="filters.outcome"
          :options="OUTCOME_OPTIONS"
          emit-value
          map-options
          outlined
          dense
          clearable
          label="Outcome"
          @update:model-value="reload"
        />
      </div>
      <div class="col-12 col-sm-6 col-md-3">
        <q-input v-model="filters.actor" outlined dense clearable debounce="300" label="User" @update:model-value="reload" />
      </div>
      <div class="col-12 col-sm-6 col-md-3">
        <q-select
          v-model="filters.device_group"
          :options="deviceGroups"
          option-value="id"
          option-label="name"
          emit-value
          map-options
          outlined
          dense
          clearable
          label="Device group"
          @update:model-value="reload"
        />
      </div>
    </div>

    <q-table
      v-model:pagination="pagination"
      flat
      :rows="entries"
      :columns="columns"
      row-key="id"
      :loading="loading"
      :rows-per-page-options="[25, 50, 100]"
      no-data-label="Nothing recorded"
      class="admin-table"
      @request="onRequest"
    >
      <template #body-cell-outcome="props">
        <q-td :props="props">
          <q-badge :color="outcomeColor(props.row.outcome)">{{ props.row.outcome }}</q-badge>
        </q-td>
      </template>
      <template #body-cell-details="props">
        <q-td :props="props">
          <q-btn
            v-if="Object.keys(props.row.details).length"
            flat
            dense
            round
            icon="info"
            color="primary"
            aria-label="Details"
            @click="shown = props.row"
          />
        </q-td>
      </template>
    </q-table>

    <q-dialog :model-value="shown !== null" @update:model-value="shown = null">
      <q-card style="width: 640px; max-width: 95vw">
        <q-card-section class="row items-center q-pb-none">
          <div class="text-h6">{{ shown?.action }}</div>
          <q-space />
          <q-btn v-close-popup icon="close" flat round dense aria-label="Close" />
        </q-card-section>
        <q-card-section>
          <div class="text-caption text-muted">{{ shown?.user_agent }}</div>
          <pre class="details">{{ JSON.stringify(shown?.details, null, 2) }}</pre>
        </q-card-section>
      </q-card>
    </q-dialog>
  </PageCard>
</template>

<script setup lang="ts">
import type { QTableColumn, QTableProps } from 'quasar'
import { onMounted, reactive, ref } from 'vue'

import { auditLogApi, deviceGroupsApi } from '@/api/endpoints'
import type { AuditEntry, AuditOutcome, DeviceGroup, Id } from '@/api/types'
import PageCard from '@/components/PageCard.vue'
import { useNotify } from '@/composables/useNotify'
import { formatDateTime } from '@/utils/datetime'

type Pagination = NonNullable<QTableProps['pagination']>

// Prefixes of the recorded actions.
const ACTION_OPTIONS = [
  { label: 'Sign-in and sessions', value: 'auth.' },
  { label: 'Users', value: 'user.' },
  { label: 'User groups and grants', value: 'user_group.' },
  { label: 'Backups', value: 'backup.' },
  { label: 'Refused requests', value: 'access.' },
  { label: 'Push receiver settings', value: 'receiver.' },
  { label: 'Refused pushes', value: 'push.' },
  { label: 'Config searches', value: 'search.' },
]
const OUTCOME_OPTIONS: { label: string; value: AuditOutcome }[] = [
  { label: 'Success', value: 'success' },
  { label: 'Failure', value: 'failure' },
  { label: 'Denied', value: 'denied' },
]
const OUTCOME_COLORS: Record<AuditOutcome, string> = { success: 'positive', failure: 'negative', denied: 'warning' }
const outcomeColor = (outcome: AuditOutcome) => OUTCOME_COLORS[outcome]

const notify = useNotify()
const entries = ref<AuditEntry[]>([])
const deviceGroups = ref<DeviceGroup[]>([])
const loading = ref(false)
const shown = ref<AuditEntry | null>(null)
const pagination = ref<Pagination>({ page: 1, rowsPerPage: 50, rowsNumber: 0 })
const filters = reactive<{ action: string | null; outcome: AuditOutcome | null; actor: string | null; device_group: Id | null }>({
  action: null,
  outcome: null,
  actor: '',
  device_group: null,
})

const columns: QTableColumn<AuditEntry>[] = [
  { name: 'created_at', label: 'When', field: 'created_at', format: formatDateTime, align: 'left' },
  { name: 'actor', label: 'User', field: 'actor_name', align: 'left' },
  { name: 'action', label: 'Action', field: 'action', align: 'left' },
  { name: 'resource', label: 'On', field: 'resource', align: 'left' },
  { name: 'device_group', label: 'Device group', field: 'device_group_name', align: 'left' },
  { name: 'outcome', label: 'Outcome', field: 'outcome', align: 'left' },
  { name: 'ip', label: 'Address', field: 'ip', align: 'left' },
  { name: 'details', label: '', field: 'id', align: 'right' },
]

async function load(): Promise<void> {
  const { page = 1, rowsPerPage = 50 } = pagination.value
  loading.value = true
  try {
    const result = await auditLogApi.list({
      page,
      page_size: rowsPerPage,
      action: filters.action ?? undefined,
      outcome: filters.outcome ?? undefined,
      actor: filters.actor || undefined,
      device_group: filters.device_group ?? undefined,
    })
    entries.value = result.results
    pagination.value = { ...pagination.value, rowsNumber: result.count }
  } catch (error) {
    notify.error(error, 'Failed to load the audit log')
  } finally {
    loading.value = false
  }
}

function reload(): void {
  pagination.value = { ...pagination.value, page: 1 }
  void load()
}

async function onRequest(request: { pagination: Pagination }): Promise<void> {
  pagination.value = { ...pagination.value, ...request.pagination }
  await load()
}

onMounted(async () => {
  void load()
  try {
    deviceGroups.value = await deviceGroupsApi.list()
  } catch {
    // The device group filter stays empty.
  }
})
</script>

<style scoped>
.details {
  margin: 8px 0 0;
  font-family: ui-monospace, SFMono-Regular, Menlo, Consolas, monospace;
  font-size: 12px;
  white-space: pre-wrap;
  word-break: break-word;
}
</style>
