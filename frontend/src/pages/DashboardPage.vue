<!-- SPDX-License-Identifier: GPL-3.0-or-later -->
<template>
  <q-page padding>
    <div class="text-h5 q-mb-md">Dashboard</div>

    <div class="row q-col-gutter-md">
      <div class="col-12 col-sm-6 col-lg-3">
        <DashboardCard title="Configured Devices">
          <div class="column no-wrap q-gutter-y-sm">
            <StatBox label="Total" :value="totalDevices" />
            <div>
              <q-list dense separator class="type-list">
                <q-item v-for="(entry, type) in stats.devicesByType" :key="type" class="q-px-sm">
                  <q-item-section avatar style="min-width: 32px">
                    <q-icon :name="entry.icon || 'router'" color="primary" />
                  </q-item-section>
                  <q-item-section>{{ type }}</q-item-section>
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
              <StatBox label="Success" :value="stats.success24h" color="positive" large />
            </div>
            <div class="col-7 column no-wrap q-gutter-y-sm">
              <StatBox label="Failed" :value="stats.failed24h" color="negative" />
              <StatBox label="In progress" :value="stats.inProgress24h" color="warning" />
            </div>
          </div>
        </DashboardCard>
      </div>

      <div class="col-12 col-sm-6 col-lg-3">
        <DashboardCard title="Average Backup Time">
          <div class="column no-wrap full-height">
            <StatBox label="Last 24h" :value="`${stats.avgDuration.toFixed(1)}s`" large />
          </div>
        </DashboardCard>
      </div>

      <div class="col-12 col-sm-6 col-lg-3">
        <DashboardCard title="Device Success Rate">
          <div class="column no-wrap full-height">
            <StatBox label="Last 24h" :value="`${stats.successRate}%`" color="positive" large />
          </div>
        </DashboardCard>
      </div>

      <div class="col-12 col-lg-5">
        <DashboardCard title="Backup Success Rate">
          <template #actions>
            <q-select
              v-model="chartDays"
              :options="DAY_OPTIONS"
              dense
              outlined
              options-dense
              emit-value
              map-options
              style="min-width: 140px"
            />
          </template>
          <SuccessChart :data="chartData" />
        </DashboardCard>
      </div>

      <div class="col-12 col-lg-7">
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
import { computed, onMounted, ref, watch } from 'vue'

import { dashboardApi } from '@/api/endpoints'
import type { ActivityItem, ActivityWindow, DailyStat, DashboardStats } from '@/api/types'
import BackupLogViewer from '@/components/BackupLogViewer.vue'
import ActivityFeed from '@/components/dashboard/ActivityFeed.vue'
import DashboardCard from '@/components/dashboard/DashboardCard.vue'
import StatBox from '@/components/dashboard/StatBox.vue'
import SuccessChart from '@/components/dashboard/SuccessChart.vue'
import type { BackupLogInfo } from '@/components/types'
import { useNotify } from '@/composables/useNotify'
import { formatDateTime } from '@/utils/datetime'
import { statusLabel } from '@/utils/format'

const DAY_OPTIONS = [
  { label: 'Last 7 days', value: 7 },
  { label: 'Last 14 days', value: 14 },
  { label: 'Last 30 days', value: 30 },
]
const WINDOW_OPTIONS: { label: string; value: ActivityWindow }[] = [
  { label: 'Last hour', value: '1h' },
  { label: 'Last 24 hours', value: '24h' },
  { label: 'Last 7 days', value: '7d' },
]

const notify = useNotify()
const stats = ref<DashboardStats>({
  devicesByType: {},
  success24h: 0,
  failed24h: 0,
  inProgress24h: 0,
  avgDuration: 0,
  successRate: 0,
  dailyStats: [],
  timezone: '',
})
const chartDays = ref(7)
const chartData = ref<DailyStat[]>([])
const activityWindow = ref<ActivityWindow>('1h')

const totalDevices = computed(() => Object.values(stats.value.devicesByType).reduce((sum, e) => sum + e.count, 0))

const logsOpen = ref(false)
const logsBackupId = ref<string | null>(null)
const logsInfo = ref<BackupLogInfo | null>(null)

function openLogs(item: ActivityItem): void {
  logsBackupId.value = item.id
  logsInfo.value = { deviceName: item.device_name, timestamp: formatDateTime(item.created_at), status: statusLabel(item.state) }
  logsOpen.value = true
}

onMounted(async () => {
  try {
    stats.value = await dashboardApi.stats()
    chartData.value = stats.value.dailyStats
  } catch (error) {
    notify.error(error, 'Failed to load dashboard statistics')
  }
})

watch(chartDays, async (days) => {
  try {
    chartData.value = (await dashboardApi.stats(days)).dailyStats
  } catch (error) {
    notify.error(error, 'Failed to load chart data')
  }
})
</script>

<style scoped>
.type-list {
  border: 3px solid var(--theme-dashboard-nested-box);
  border-radius: 8px;
}
</style>
