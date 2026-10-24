<!-- SPDX-License-Identifier: GPL-3.0-or-later -->
<!-- The latest pushes a receiver refused: useful when a device is set up with the wrong address or login. -->
<template>
  <FormDialog v-model="open" :title="`Refused pushes · ${worker?.name ?? ''}`" readonly width="900px">
    <q-table
      flat
      dense
      :rows="rows"
      :columns="columns"
      row-key="id"
      :loading="loading"
      :pagination="{ rowsPerPage: 15 }"
      no-data-label="Nothing has been refused."
    >
      <template #body-cell-at="props">
        <q-td :props="props"><TimeCell :value="props.row.at" /></q-td>
      </template>
      <template #body-cell-reason="props">
        <q-td :props="props">
          <div>{{ reasonLabel(props.row.reason) }}</div>
          <div v-if="props.row.detail" class="text-caption text-grey">{{ props.row.detail }}</div>
        </q-td>
      </template>
    </q-table>
  </FormDialog>
</template>

<script setup lang="ts">
import type { QTableColumn } from 'quasar'
import { ref, watch } from 'vue'

import { workersApi } from '@/api/endpoints'
import type { PushRejection, PushRejectionReason, Worker } from '@/api/types'
import FormDialog from '@/components/FormDialog.vue'
import TimeCell from '@/components/TimeCell.vue'
import { useNotify } from '@/composables/useNotify'
import { pushProtocolLabel } from '@/utils/format'

const props = defineProps<{ worker: Worker | null }>()
const open = defineModel<boolean>({ required: true })
const REASONS: Record<PushRejectionReason, string> = {
  unknown_source: 'Unknown source address',
  auth_failed: 'Login failed',
  wrong_protocol: 'Wrong protocol for the device',
  filename: 'File name not accepted',
  too_large: 'File too large',
  device_changed: 'Device changed meanwhile',
  error: 'Could not be stored',
}
const reasonLabel = (reason: PushRejectionReason) => REASONS[reason] ?? reason

const notify = useNotify()
const rows = ref<PushRejection[]>([])
const loading = ref(false)

const columns: QTableColumn<PushRejection>[] = [
  { name: 'at', label: 'When', field: 'at', align: 'left' },
  { name: 'source_ip', label: 'Source', field: 'source_ip', align: 'left' },
  { name: 'protocol', label: 'Protocol', field: 'protocol', align: 'left', format: pushProtocolLabel },
  { name: 'reason', label: 'Reason', field: 'reason', align: 'left' },
  { name: 'filename', label: 'File', field: 'filename', align: 'left' },
]

watch(open, async (isOpen) => {
  if (!isOpen || !props.worker) return
  loading.value = true
  try {
    rows.value = await workersApi.rejections(props.worker.id)
  } catch (error) {
    notify.error(error, 'Failed to load refused pushes')
  } finally {
    loading.value = false
  }
})
</script>
