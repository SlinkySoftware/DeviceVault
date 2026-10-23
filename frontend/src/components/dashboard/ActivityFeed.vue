<!-- SPDX-License-Identifier: GPL-3.0-or-later -->
<!-- Recent backups; refreshes every 30s, or every 5s while any are in flight. -->
<template>
  <q-table
    flat
    dense
    :rows="items"
    :columns="columns"
    row-key="id"
    :loading="loading"
    :pagination="{ rowsPerPage: 0 }"
    hide-bottom
    virtual-scroll
    class="activity-table"
    no-data-label="No recent backup activity"
  >
    <template #body-cell-created_at="props">
      <q-td :props="props">
        <span :title="formatDateTime(props.row.created_at)">{{ formatRelativeTime(props.row.created_at) }}</span>
      </q-td>
    </template>
    <template #body-cell-state="props">
      <q-td :props="props">
        <StatusLabel :status="props.row.state" />
        <q-tooltip v-if="props.row.error">{{ props.row.error }}</q-tooltip>
      </q-td>
    </template>
    <template #body-cell-log="props">
      <q-td :props="props">
        <q-btn v-if="props.row.has_log" flat dense no-caps color="primary" label="View log" @click="emit('view-logs', props.row)" />
      </q-td>
    </template>
  </q-table>
</template>

<script setup lang="ts">
import type { QTableColumn } from 'quasar'
import { computed, ref, watch } from 'vue'

import { dashboardApi } from '@/api/endpoints'
import type { ActivityItem, ActivityWindow } from '@/api/types'
import StatusLabel from '@/components/StatusLabel.vue'
import { usePolling } from '@/composables/usePolling'
import { formatDateTime, formatRelativeTime } from '@/utils/datetime'
import { capitalise, formatDuration, isActiveJob } from '@/utils/format'

const props = defineProps<{ window: ActivityWindow }>()
const emit = defineEmits<{ 'view-logs': [item: ActivityItem] }>()

const items = ref<ActivityItem[]>([])
const loading = ref(false)
const inFlight = computed(() => items.value.some((item) => isActiveJob(item.state)))
const interval = computed(() => (inFlight.value ? 5_000 : 30_000))

const columns: QTableColumn<ActivityItem>[] = [
  { name: 'created_at', label: 'When', field: 'created_at', align: 'left' },
  { name: 'device_name', label: 'Device', field: 'device_name', align: 'left' },
  { name: 'state', label: 'Backup', field: 'state', align: 'left' },
  { name: 'trigger', label: 'Trigger', field: 'trigger', format: capitalise, align: 'left' },
  { name: 'duration', label: 'Took', field: 'duration_ms', format: formatDuration, align: 'right' },
  { name: 'log', label: '', field: 'id', align: 'right' },
]

async function load(): Promise<void> {
  loading.value = items.value.length === 0
  try {
    items.value = await dashboardApi.activity(props.window)
  } catch {
    items.value = []
  } finally {
    loading.value = false
  }
}

usePolling(load, interval)
watch(() => props.window, load)
</script>

<style scoped>
.activity-table {
  max-height: 420px;
}
</style>
