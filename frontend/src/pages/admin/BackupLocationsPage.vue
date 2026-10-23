<!-- SPDX-License-Identifier: GPL-3.0-or-later -->
<template>
  <PageCard title="Backup Locations" caption="Where storage workers keep device backups">
    <template #actions>
      <q-btn color="primary" icon="add" label="Add Location" @click="crud.openCreate" />
    </template>

    <q-table flat :rows="crud.rows.value" :columns="columns" row-key="id" :loading="crud.loading.value" class="admin-table">
      <template #body-cell-actions="props">
        <q-td :props="props">
          <RowActions @edit="crud.openEdit(props.row)" @delete="crud.confirmRemove(props.row)" />
        </q-td>
      </template>
    </q-table>

    <FormDialog
      v-model="crud.dialogOpen.value"
      :title="crud.isEditing.value ? 'Edit Backup Location' : 'Add Backup Location'"
      :saving="crud.saving.value"
      width="600px"
      @submit="crud.save"
    >
      <q-input v-model.trim="crud.form.value.name" label="Name" outlined autofocus :rules="[required]" />
      <q-select
        v-model="crud.form.value.location_type"
        :options="LOCATION_TYPES"
        emit-value
        map-options
        label="Location type"
        outlined
        :rules="[required]"
      />
      <JsonEditor v-model="crud.form.value.config" label="Configuration (JSON)" :hint="configHint" />
    </FormDialog>
  </PageCard>
</template>

<script setup lang="ts">
import type { QTableColumn } from 'quasar'
import { computed } from 'vue'

import { backupLocationsApi } from '@/api/endpoints'
import type { BackupLocation, BackupLocationWrite } from '@/api/types'
import FormDialog from '@/components/FormDialog.vue'
import JsonEditor from '@/components/JsonEditor.vue'
import PageCard from '@/components/PageCard.vue'
import RowActions from '@/components/RowActions.vue'
import { useCrud } from '@/composables/useCrud'
import { required } from '@/utils/rules'

// Only backends a storage worker can serve today; more arrive with storage drivers.
const LOCATION_TYPES = [
  { label: 'Filesystem', value: 'filesystem' },
  { label: 'Git repository', value: 'git' },
]

const HINTS: Record<string, string> = {
  filesystem: 'e.g. {"path": "/srv/devicevault/backups", "compress": true}',
  git: 'e.g. {"path": "/srv/devicevault/repo", "branch": "main"}',
}

const crud = useCrud<BackupLocation, BackupLocationWrite>({
  api: backupLocationsApi,
  noun: 'backup location',
  emptyForm: () => ({ name: '', location_type: 'filesystem', config: {} }),
  toForm: (row) => ({ name: row.name, location_type: row.location_type, config: { ...(row.config ?? {}) } }),
})

const configHint = computed(
  () => `${HINTS[crud.form.value.location_type] ?? ''} Paths must be under /srv/devicevault on the storage worker.`,
)

const columns: QTableColumn<BackupLocation>[] = [
  { name: 'name', label: 'Name', field: 'name', align: 'left', sortable: true },
  { name: 'type', label: 'Type', field: 'location_type', align: 'left', sortable: true },
  { name: 'actions', label: 'Actions', field: 'id', align: 'right' },
]
</script>
