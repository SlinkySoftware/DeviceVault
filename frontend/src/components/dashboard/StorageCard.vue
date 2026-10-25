<!-- SPDX-License-Identifier: GPL-3.0-or-later -->
<!-- What each storage target holds for the devices the user can see. -->
<template>
  <DashboardCard
    title="Storage by Target"
    caption="Size the collectors reported; targets that deduplicate or compress (git, some S3) use less on disk"
    :loading="loading"
    :failed="failed"
    @retry="refresh"
  >
    <BarList :rows="rows" label="Stored size by storage target" empty-text="No stored backups" class="q-pa-sm" />
  </DashboardCard>
</template>

<script setup lang="ts">
import { computed } from 'vue'

import { dashboardApi } from '@/api/endpoints'
import type { DashboardPeriod } from '@/api/types'
import BarList from '@/components/charts/BarList.vue'
import type { BarRow } from '@/components/charts/types'
import DashboardCard from '@/components/dashboard/DashboardCard.vue'
import { useCardData } from '@/composables/useCardData'
import { formatBytes } from '@/utils/format'

const props = defineProps<{ days: DashboardPeriod }>()

const { data, loading, failed, refresh } = useCardData(
  () => dashboardApi.storage(props.days),
  () => props.days,
)

const plural = (n: number, word: string) => `${n.toLocaleString()} ${word}${n === 1 ? '' : 's'}`

const rows = computed<BarRow[]>(() =>
  (data.value ?? []).map((target) => ({
    key: target.storage_target,
    label: `${target.name} (${target.driver})`,
    value: target.size_bytes,
    display: `${formatBytes(target.size_bytes)} · ${plural(target.backups, 'backup')}`,
    caption: `+${formatBytes(target.added_bytes)} in ${plural(target.added_backups, 'backup')}, last ${props.days} days`,
  })),
)
</script>
