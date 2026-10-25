<!-- SPDX-License-Identifier: GPL-3.0-or-later -->
<!-- The devices with the most failed backups in the period. -->
<template>
  <DashboardCard title="Top Failing Devices" :caption="`Most failed backups, last ${days} days`" :loading="loading" :failed="failed" @retry="refresh">
    <q-table
      flat
      dense
      :rows="data ?? []"
      :columns="columns"
      row-key="device"
      :pagination="{ rowsPerPage: 0 }"
      hide-bottom
      no-data-label="No failed backups in this period"
    >
      <template #body-cell-device="props">
        <q-td :props="props">
          <router-link class="text-link" :to="{ name: 'device-backups', params: { id: props.row.device } }">{{ props.row.device_name }}</router-link>
          <q-tooltip v-if="props.row.error" max-width="420px">{{ props.row.error }}</q-tooltip>
        </q-td>
      </template>
      <template #body-cell-last_failed="props">
        <q-td :props="props">
          <span :title="formatDateTime(props.row.last_failed)">{{ formatRelativeTime(props.row.last_failed) }}</span>
        </q-td>
      </template>
      <template #body-cell-state="props">
        <q-td :props="props">
          <span v-if="props.row.recovered" class="row inline items-center no-wrap q-gutter-x-xs">
            <q-icon name="check_circle" color="positive" /><span>Recovered</span>
          </span>
          <span v-else class="row inline items-center no-wrap q-gutter-x-xs">
            <q-icon name="error" color="negative" /><span>Failing</span>
          </span>
        </q-td>
      </template>
    </q-table>
  </DashboardCard>
</template>

<script setup lang="ts">
import type { QTableColumn } from 'quasar'

import { dashboardApi } from '@/api/endpoints'
import type { DashboardPeriod, FailingDevice } from '@/api/types'
import DashboardCard from '@/components/dashboard/DashboardCard.vue'
import { useCardData } from '@/composables/useCardData'
import { formatDateTime, formatRelativeTime } from '@/utils/datetime'

const props = defineProps<{ days: DashboardPeriod }>()

const { data, loading, failed, refresh } = useCardData(
  () => dashboardApi.failing(props.days),
  () => props.days,
)

const columns: QTableColumn<FailingDevice>[] = [
  { name: 'device', label: 'Device', field: 'device_name', align: 'left' },
  { name: 'failed', label: 'Failed', field: 'failed', align: 'right' },
  { name: 'stored', label: 'Stored', field: 'stored', align: 'right' },
  { name: 'last_failed', label: 'Last failed', field: 'last_failed', align: 'left' },
  { name: 'state', label: 'Now', field: 'recovered', align: 'left' },
]
</script>
