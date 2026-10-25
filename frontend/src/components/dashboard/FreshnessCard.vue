<!-- SPDX-License-Identifier: GPL-3.0-or-later -->
<!-- How old each device group's latest successful backups are, stalest group first. -->
<template>
  <DashboardCard
    title="Backup Freshness"
    caption="Latest successful backup of each enabled device"
    :loading="loading"
    :failed="failed"
    @retry="refresh"
  >
    <q-table
      flat
      dense
      :rows="data ?? []"
      :columns="columns"
      :row-key="(row: GroupFreshness) => String(row.device_group)"
      :pagination="{ rowsPerPage: 0 }"
      hide-bottom
      no-data-label="No enabled devices"
      class="freshness-table"
    >
      <template #body-cell-never="props">
        <q-td :props="props" :class="{ 'text-negative text-weight-bold': props.row.never }">{{ props.row.never }}</q-td>
      </template>
      <template #body-cell-older_7d="props">
        <q-td :props="props" :class="{ 'text-warning text-weight-bold': props.row.older_7d }">{{ props.row.older_7d }}</q-td>
      </template>
      <template #body-cell-stalest="props">
        <q-td :props="props">
          <router-link class="text-link" :to="{ name: 'device-backups', params: { id: props.row.stalest.id } }">{{ props.row.stalest.name }}</router-link>
          <div class="text-caption text-muted" :title="formatDateTime(props.row.stalest.last_success)">
            {{ props.row.stalest.last_success ? formatRelativeTime(props.row.stalest.last_success) : 'Never backed up' }}
          </div>
        </q-td>
      </template>
    </q-table>
  </DashboardCard>
</template>

<script setup lang="ts">
import type { QTableColumn } from 'quasar'

import { dashboardApi } from '@/api/endpoints'
import type { GroupFreshness } from '@/api/types'
import DashboardCard from '@/components/dashboard/DashboardCard.vue'
import { useCardData } from '@/composables/useCardData'
import { formatDateTime, formatRelativeTime } from '@/utils/datetime'

const { data, loading, failed, refresh } = useCardData(() => dashboardApi.freshness())

const columns: QTableColumn<GroupFreshness>[] = [
  { name: 'group', label: 'Device group', field: (row) => row.device_group_name || 'No group', align: 'left' },
  { name: 'stalest', label: 'Stalest device', field: (row) => row.stalest.name, align: 'left' },
  { name: 'devices', label: 'Devices', field: 'devices', align: 'right' },
  { name: 'never', label: 'Never', field: 'never', align: 'right' },
  { name: 'older_24h', label: 'Over 24 h', field: 'older_24h', align: 'right' },
  { name: 'older_7d', label: 'Over 7 days', field: 'older_7d', align: 'right' },
]
</script>

<style scoped>
.freshness-table {
  max-height: 360px;
}
</style>
