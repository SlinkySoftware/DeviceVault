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
      :left-title="`A · ${formatDateTime(older.meta.timestamp)}`"
      :right-title="`B · ${formatDateTime(newer.meta.timestamp)}`"
    />
  </PageCard>
</template>

<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'
import { useRoute } from 'vue-router'

import { apiErrorMessage } from '@/api/client'
import { storedBackupsApi } from '@/api/endpoints'
import type { Id, StoredBackup } from '@/api/types'
import DiffView from '@/components/DiffView.vue'
import PageCard from '@/components/PageCard.vue'
import { formatDateTime } from '@/utils/datetime'

interface Side {
  meta: StoredBackup
  content: string
}

const route = useRoute()
const deviceId = computed(() => Number(route.params.id))

const older = ref<Side | null>(null)
const newer = ref<Side | null>(null)
const loading = ref(true)
const error = ref('')

async function loadSide(id: Id): Promise<Side> {
  const [meta, content] = await Promise.all([storedBackupsApi.get(id), storedBackupsApi.downloadText(id)])
  return { meta, content }
}

onMounted(async () => {
  const a = Number(route.query.a)
  const b = Number(route.query.b)
  if (!Number.isInteger(a) || !Number.isInteger(b)) {
    error.value = 'Choose two backups to compare.'
    loading.value = false
    return
  }
  try {
    const sides = await Promise.all([loadSide(a), loadSide(b)])
    sides.sort((x, y) => new Date(x.meta.timestamp).getTime() - new Date(y.meta.timestamp).getTime())
    ;[older.value, newer.value] = sides
  } catch (exc) {
    error.value = apiErrorMessage(exc, 'Failed to load backups for comparison')
  } finally {
    loading.value = false
  }
})
</script>
