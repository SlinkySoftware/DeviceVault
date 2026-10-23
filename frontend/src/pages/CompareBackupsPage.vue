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
      :left-title="`A · ${formatDateTime(older.meta.created_at)}`"
      :right-title="`B · ${formatDateTime(newer.meta.created_at)}`"
    />
  </PageCard>
</template>

<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'
import { useRoute } from 'vue-router'

import { apiErrorMessage } from '@/api/client'
import { backupJobsApi } from '@/api/endpoints'
import type { BackupJob } from '@/api/types'
import DiffView from '@/components/DiffView.vue'
import PageCard from '@/components/PageCard.vue'
import { formatDateTime } from '@/utils/datetime'

interface Side {
  meta: BackupJob
  content: string
}

const route = useRoute()
const deviceId = computed(() => Number(route.params.id))

const older = ref<Side | null>(null)
const newer = ref<Side | null>(null)
const loading = ref(true)
const error = ref('')

async function loadSide(id: string): Promise<Side> {
  const [meta, content] = await Promise.all([backupJobsApi.get(id), backupJobsApi.contentText(id)])
  return { meta, content }
}

onMounted(async () => {
  const a = typeof route.query.a === 'string' ? route.query.a : ''
  const b = typeof route.query.b === 'string' ? route.query.b : ''
  if (!a || !b) {
    error.value = 'Choose two backups to compare.'
    loading.value = false
    return
  }
  try {
    const sides = await Promise.all([loadSide(a), loadSide(b)])
    sides.sort((x, y) => new Date(x.meta.created_at).getTime() - new Date(y.meta.created_at).getTime())
    ;[older.value, newer.value] = sides
  } catch (exc) {
    error.value = apiErrorMessage(exc, 'Failed to load backups for comparison')
  } finally {
    loading.value = false
  }
})
</script>
