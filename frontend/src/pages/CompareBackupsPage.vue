<!-- SPDX-License-Identifier: GPL-3.0-or-later -->
<template>
  <PageCard title="Compare Backups" caption="Older backup on the left, newer on the right">
    <template #actions>
      <q-btn color="primary" icon="arrow_back" label="Back to Backups" :to="{ name: 'device-backups', params: { id: deviceId } }" />
    </template>

    <div v-if="loading" class="text-center q-pa-lg">
      <q-spinner color="primary" size="50px" />
    </div>
    <div v-else-if="error" class="text-center text-negative q-pa-lg">{{ error }}</div>
    <DiffView
      v-else-if="older && newer"
      :left="older.content"
      :right="newer.content"
      :left-title="title('A', older)"
      :right-title="title('B', newer)"
    />
  </PageCard>
</template>

<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'
import { useRoute } from 'vue-router'

import { apiErrorMessage } from '@/api/client'
import { backupJobsApi } from '@/api/endpoints'
import type { ComparedBackup } from '@/api/types'
import DiffView from '@/components/DiffView.vue'
import PageCard from '@/components/PageCard.vue'
import { formatDateTime } from '@/utils/datetime'

const route = useRoute()
const deviceId = computed(() => Number(route.params.id))

const older = ref<ComparedBackup | null>(null)
const newer = ref<ComparedBackup | null>(null)
const loading = ref(true)
const error = ref('')

const title = (side: string, backup: ComparedBackup) =>
  [side, formatDateTime(backup.job.created_at), backup.job.label].filter(Boolean).join(' · ')

onMounted(async () => {
  const a = typeof route.query.a === 'string' ? route.query.a : ''
  const b = typeof route.query.b === 'string' ? route.query.b : ''
  if (!a || !b) {
    error.value = 'Choose two backups to compare.'
    loading.value = false
    return
  }
  try {
    const { a: first, b: second } = await backupJobsApi.compare(a, b)
    const swap = new Date(first.job.created_at).getTime() > new Date(second.job.created_at).getTime()
    ;[older.value, newer.value] = swap ? [second, first] : [first, second]
  } catch (exc) {
    error.value = apiErrorMessage(exc, 'Failed to load backups for comparison')
  } finally {
    loading.value = false
  }
})
</script>
