<!-- SPDX-License-Identifier: GPL-3.0-or-later -->
<!-- Pushes the receivers refused: per day, by reason, and the sources sending most. Global administrators only. -->
<template>
  <DashboardCard
    title="Push Refusals"
    caption="At least this many: receivers rate-limit refusal reports"
    :loading="loading"
    :failed="failed"
    @retry="refresh"
  >
    <TimeSeriesChart
      :dates="dates"
      :series="series"
      kind="bar"
      integer
      :height="160"
      label="Push refusals per day"
      empty-text="No refused pushes in this period"
    />
    <div v-if="data && data.by_reason.length" class="row q-col-gutter-md q-mt-sm">
      <div class="col-12">
        <div class="text-subtitle2 q-mb-xs">By reason</div>
        <BarList :rows="reasons" label="Push refusals by reason" />
      </div>
      <div class="col-12">
        <div class="text-subtitle2 q-mb-xs">Top sources</div>
        <q-table flat dense :rows="data.sources" :columns="columns" row-key="source_ip" :pagination="{ rowsPerPage: 0 }" hide-bottom>
          <template #body-cell-last_at="props">
            <q-td :props="props">
              <span :title="formatDateTime(props.row.last_at)">{{ formatRelativeTime(props.row.last_at) }}</span>
            </q-td>
          </template>
        </q-table>
      </div>
    </div>
  </DashboardCard>
</template>

<script setup lang="ts">
import type { QTableColumn } from 'quasar'
import { computed } from 'vue'

import { dashboardApi } from '@/api/endpoints'
import type { DashboardPeriod, PushRefusals } from '@/api/types'
import BarList from '@/components/charts/BarList.vue'
import TimeSeriesChart from '@/components/charts/TimeSeriesChart.vue'
import type { BarRow, ChartSeries } from '@/components/charts/types'
import DashboardCard from '@/components/dashboard/DashboardCard.vue'
import { useCardData } from '@/composables/useCardData'
import { formatDateTime, formatRelativeTime } from '@/utils/datetime'
import { pushReasonLabel } from '@/utils/format'

const props = defineProps<{ days: DashboardPeriod }>()

const { data, loading, failed, refresh } = useCardData(
  () => dashboardApi.pushRefusals(props.days),
  () => props.days,
)

const dates = computed(() => (data.value?.days ?? []).map((day) => day.date))
const series = computed<ChartSeries[]>(() => [
  { key: 'count', label: 'Refused', color: 'var(--chart-1)', values: (data.value?.days ?? []).map((day) => day.count) },
])
const reasons = computed<BarRow[]>(() =>
  (data.value?.by_reason ?? []).map((row) => ({
    key: row.reason,
    label: pushReasonLabel(row.reason),
    value: row.count,
    display: row.count.toLocaleString(),
  })),
)

type Source = PushRefusals['sources'][number]
const columns: QTableColumn<Source>[] = [
  { name: 'source_ip', label: 'Source', field: 'source_ip', align: 'left' },
  { name: 'count', label: 'Refused', field: 'count', align: 'right' },
  { name: 'last_reason', label: 'Latest reason', field: (row) => pushReasonLabel(row.last_reason), align: 'left' },
  { name: 'receiver', label: 'Receiver', field: 'receiver', align: 'left' },
  { name: 'last_at', label: 'Last', field: 'last_at', align: 'left' },
]
</script>
