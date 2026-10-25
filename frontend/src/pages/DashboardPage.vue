<!-- SPDX-License-Identifier: GPL-3.0-or-later -->
<template>
  <q-page padding>
    <div class="row items-center q-mb-md q-gutter-sm">
      <div class="text-h5 col-auto q-mr-md">Dashboard</div>
      <q-btn-toggle
        :model-value="days"
        :options="PERIOD_OPTIONS"
        dense
        no-caps
        unelevated
        toggle-color="primary"
        class="period-toggle"
        aria-label="Period"
        @update:model-value="setDays"
      />
    </div>

    <div class="row q-col-gutter-md">
      <div class="col-12 col-sm-6 col-lg-3">
        <DashboardCard title="Configured Devices" :failed="summaryCard.failed.value" @retry="summaryCard.refresh">
          <div class="column no-wrap q-gutter-y-sm">
            <StatBox label="Total" :value="totalDevices" />
            <div>
              <q-list dense separator class="type-list">
                <q-item v-for="entry in summary?.devices_by_type ?? []" :key="entry.name" class="q-px-sm">
                  <q-item-section avatar style="min-width: 32px">
                    <q-icon :name="entry.icon || 'router'" color="primary" />
                  </q-item-section>
                  <q-item-section>{{ entry.name || 'No type' }}</q-item-section>
                  <q-item-section side class="text-subtitle1 text-weight-bold text-primary">{{ entry.count }}</q-item-section>
                </q-item>
              </q-list>
              <div v-if="totalDevices === 0" class="text-caption text-grey q-pa-sm">No devices</div>
            </div>
          </div>
        </DashboardCard>
      </div>

      <div class="col-12 col-sm-6 col-lg-3">
        <DashboardCard title="Backups (24h)">
          <div class="row q-col-gutter-sm full-height">
            <div class="col-5 column no-wrap">
              <StatBox label="Stored" :value="summary?.stored_24h ?? 0" color="positive" large />
            </div>
            <div class="col-7 column no-wrap q-gutter-y-sm">
              <StatBox label="Failed" :value="summary?.failed_24h ?? 0" color="negative" />
              <StatBox label="In progress" :value="summary?.in_progress ?? 0" color="warning" />
            </div>
          </div>
        </DashboardCard>
      </div>

      <div class="col-12 col-sm-6 col-lg-3">
        <DashboardCard title="Average Backup Time">
          <div class="column no-wrap full-height">
            <StatBox label="Last 24h" :value="`${(summary?.avg_duration_s ?? 0).toFixed(1)}s`" large />
          </div>
        </DashboardCard>
      </div>

      <div class="col-12 col-sm-6 col-lg-3">
        <DashboardCard title="Device Success Rate">
          <div class="column no-wrap full-height">
            <StatBox
              label="Latest backup succeeded"
              :value="summary?.device_success_rate == null ? '—' : `${summary.device_success_rate}%`"
              color="positive"
              large
            />
          </div>
        </DashboardCard>
      </div>

      <div class="col-12 col-lg-6">
        <DashboardCard
          title="Backups per Day"
          :caption="`Stored and failed, last ${days} days`"
          :loading="trendCard.loading.value"
          :failed="trendCard.failed.value"
          @retry="trendCard.refresh"
        >
          <TimeSeriesChart :dates="dates" :series="volume" kind="bar" integer label="Stored and failed backups per day" />
        </DashboardCard>
      </div>

      <div class="col-12 col-lg-6">
        <DashboardCard
          title="Success Rate"
          caption="Stored backups of those finished each day"
          :loading="trendCard.loading.value"
          :failed="trendCard.failed.value"
          @retry="trendCard.refresh"
        >
          <TimeSeriesChart :dates="dates" :series="rate" :max="100" :format="percent" label="Backup success rate per day" />
        </DashboardCard>
      </div>

      <div class="col-12 col-lg-6">
        <DashboardCard
          title="Backup Duration"
          caption="Request to stored"
          :loading="trendCard.loading.value"
          :failed="trendCard.failed.value"
          @retry="trendCard.refresh"
        >
          <TimeSeriesChart :dates="dates" :series="duration" :format="seconds" label="Average and longest backup duration per day" />
        </DashboardCard>
      </div>

      <div class="col-12 col-lg-6">
        <DashboardCard
          title="Changes per Day"
          caption="Stored backups that differ from the device's previous one"
          :loading="trendCard.loading.value"
          :failed="trendCard.failed.value"
          @retry="trendCard.refresh"
        >
          <TimeSeriesChart
            :dates="dates"
            :series="changes"
            kind="bar"
            integer
            label="Changed backups per day"
            empty-text="No changes in this period"
          />
        </DashboardCard>
      </div>

      <div class="col-12 col-lg-6">
        <FreshnessCard />
      </div>

      <div class="col-12 col-lg-6">
        <FailingCard :days="days" />
      </div>

      <div class="col-12 col-lg-6">
        <StorageCard :days="days" />
      </div>

      <div v-if="auth.isGlobalAdmin" class="col-12 col-lg-6">
        <PushRefusalsCard :days="days" />
      </div>

      <div class="col-12">
        <DashboardCard title="Recent Backup Activity">
          <template #actions>
            <q-select
              v-model="activityWindow"
              :options="WINDOW_OPTIONS"
              dense
              outlined
              options-dense
              emit-value
              map-options
              style="min-width: 150px"
            />
          </template>
          <ActivityFeed :window="activityWindow" @view-logs="openLogs" />
        </DashboardCard>
      </div>
    </div>

    <BackupLogViewer v-model="logsOpen" :backup-id="logsBackupId" :info="logsInfo" />
  </q-page>
</template>

<script setup lang="ts">
import { computed, ref } from 'vue'
import { useRoute, useRouter } from 'vue-router'

import { dashboardApi } from '@/api/endpoints'
import type { ActivityItem, ActivityWindow, DashboardPeriod } from '@/api/types'
import BackupLogViewer from '@/components/BackupLogViewer.vue'
import TimeSeriesChart from '@/components/charts/TimeSeriesChart.vue'
import type { ChartSeries } from '@/components/charts/types'
import ActivityFeed from '@/components/dashboard/ActivityFeed.vue'
import DashboardCard from '@/components/dashboard/DashboardCard.vue'
import FailingCard from '@/components/dashboard/FailingCard.vue'
import FreshnessCard from '@/components/dashboard/FreshnessCard.vue'
import PushRefusalsCard from '@/components/dashboard/PushRefusalsCard.vue'
import StatBox from '@/components/dashboard/StatBox.vue'
import StorageCard from '@/components/dashboard/StorageCard.vue'
import type { BackupLogInfo } from '@/components/types'
import { useCardData } from '@/composables/useCardData'
import { useAuthStore } from '@/stores/auth'
import { formatDateTime } from '@/utils/datetime'
import { statusLabel } from '@/utils/format'

const PERIODS: DashboardPeriod[] = [7, 14, 30, 90]
const DEFAULT_PERIOD: DashboardPeriod = 30
const PERIOD_OPTIONS = PERIODS.map((value) => ({ label: `${value} days`, value }))
const WINDOW_OPTIONS: { label: string; value: ActivityWindow }[] = [
  { label: 'Last hour', value: '1h' },
  { label: 'Last 24 hours', value: '24h' },
  { label: 'Last 7 days', value: '7d' },
]

const auth = useAuthStore()
const route = useRoute()
const router = useRouter()

// The period lives in the URL (?days=30) so a view can be shared.
const days = computed<DashboardPeriod>(() => {
  const value = Number(route.query.days)
  return PERIODS.includes(value as DashboardPeriod) ? (value as DashboardPeriod) : DEFAULT_PERIOD
})
function setDays(value: DashboardPeriod): void {
  void router.replace({ query: { ...route.query, days: String(value) } })
}

const summaryCard = useCardData(() => dashboardApi.summary())
const summary = summaryCard.data
const totalDevices = computed(() => (summary.value?.devices_by_type ?? []).reduce((sum, e) => sum + e.count, 0))

const trendCard = useCardData(
  () => dashboardApi.trend(days.value),
  () => days.value,
)
const trend = computed(() => trendCard.data.value?.days ?? [])
const dates = computed(() => trend.value.map((day) => day.date))
const volume = computed<ChartSeries[]>(() => [
  { key: 'stored', label: 'Stored', color: 'var(--chart-1)', values: trend.value.map((day) => day.stored) },
  { key: 'failed', label: 'Failed', color: 'var(--chart-failed)', values: trend.value.map((day) => day.failed) },
])
const rate = computed<ChartSeries[]>(() => [
  { key: 'rate', label: 'Success rate', color: 'var(--chart-1)', values: trend.value.map((day) => day.rate) },
])
const duration = computed<ChartSeries[]>(() => [
  { key: 'avg', label: 'Average', color: 'var(--chart-1)', values: trend.value.map((day) => day.avg_duration_s) },
  { key: 'max', label: 'Longest', color: 'var(--chart-2)', values: trend.value.map((day) => day.max_duration_s) },
])
const changes = computed<ChartSeries[]>(() => [
  { key: 'changed', label: 'Changed', color: 'var(--chart-1)', values: trend.value.map((day) => day.changed) },
])
const percent = (value: number) => `${Math.round(value)}%`
const seconds = (value: number) => (value >= 60 ? `${Math.round(value / 6) / 10} min` : `${Math.round(value * 10) / 10} s`)

const activityWindow = ref<ActivityWindow>('1h')
const logsOpen = ref(false)
const logsBackupId = ref<string | null>(null)
const logsInfo = ref<BackupLogInfo | null>(null)

function openLogs(item: ActivityItem): void {
  logsBackupId.value = item.id
  logsInfo.value = { deviceName: item.device_name, timestamp: formatDateTime(item.created_at), status: statusLabel(item.state) }
  logsOpen.value = true
}
</script>

<style scoped>
.type-list {
  border: var(--nested-border);
  background: var(--nested-bg);
  border-radius: 8px;
}

.period-toggle {
  border: 1px solid var(--border-color-muted);
}
</style>
