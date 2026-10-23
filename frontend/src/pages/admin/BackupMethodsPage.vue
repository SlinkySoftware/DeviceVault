<!-- SPDX-License-Identifier: GPL-3.0-or-later -->
<template>
  <PageCard title="Backup Methods" caption="Collector plugins available to devices (read-only)">
    <q-table flat :rows="methods" :columns="columns" row-key="key" :loading="loading" class="admin-table">
      <template #body-cell-friendly_name="props">
        <q-td :props="props">
          <strong>{{ props.row.friendly_name }}</strong>
          <div class="text-caption text-grey">{{ props.row.key }}</div>
        </q-td>
      </template>
      <template #body-cell-is_binary="props">
        <q-td :props="props">
          <q-badge :color="props.row.is_binary ? 'purple' : 'blue-grey'" :label="props.row.is_binary ? 'Binary' : 'Text'" />
        </q-td>
      </template>
    </q-table>
  </PageCard>
</template>

<script setup lang="ts">
import type { QTableColumn } from 'quasar'
import { onMounted, ref } from 'vue'

import { backupMethodsApi } from '@/api/endpoints'
import type { BackupMethod } from '@/api/types'
import PageCard from '@/components/PageCard.vue'
import { useNotify } from '@/composables/useNotify'

const notify = useNotify()
const methods = ref<BackupMethod[]>([])
const loading = ref(false)

const columns: QTableColumn<BackupMethod>[] = [
  { name: 'friendly_name', label: 'Backup Method', field: 'friendly_name', align: 'left', sortable: true },
  { name: 'is_binary', label: 'Output', field: 'is_binary', align: 'center' },
  { name: 'description', label: 'Description', field: 'description', align: 'left' },
]

onMounted(async () => {
  loading.value = true
  try {
    methods.value = await backupMethodsApi.list()
  } catch (error) {
    notify.error(error, 'Failed to load backup methods')
  } finally {
    loading.value = false
  }
})
</script>
