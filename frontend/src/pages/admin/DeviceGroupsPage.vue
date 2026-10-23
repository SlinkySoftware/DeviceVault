<!-- SPDX-License-Identifier: GPL-3.0-or-later -->
<template>
  <PageCard title="Device Groups" caption="Groups control who can see and manage devices; their roles are created automatically">
    <template #actions>
      <q-btn color="primary" icon="add" label="Add Device Group" @click="crud.openCreate" />
    </template>

    <q-table flat :rows="crud.rows.value" :columns="columns" row-key="id" :loading="crud.loading.value" class="admin-table">
      <template #body-cell-description="props">
        <q-td :props="props">
          <span v-if="props.row.description">{{ props.row.description }}</span>
          <span v-else class="text-muted">No description</span>
        </q-td>
      </template>
      <template #body-cell-actions="props">
        <q-td :props="props">
          <RowActions
            @edit="crud.openEdit(props.row)"
            @delete="crud.confirmRemove(props.row, 'Deletion is blocked while devices or role members remain.')"
          />
        </q-td>
      </template>
    </q-table>

    <FormDialog
      v-model="crud.dialogOpen.value"
      :title="crud.isEditing.value ? 'Edit Device Group' : 'Add Device Group'"
      :saving="crud.saving.value"
      @submit="crud.save"
    >
      <q-input v-model.trim="crud.form.value.name" label="Name" outlined autofocus :rules="[required]" />
      <q-input v-model="crud.form.value.description" label="Description" type="textarea" autogrow outlined />
    </FormDialog>
  </PageCard>
</template>

<script setup lang="ts">
import type { QTableColumn } from 'quasar'

import { deviceGroupsApi } from '@/api/endpoints'
import type { DeviceGroup } from '@/api/types'
import FormDialog from '@/components/FormDialog.vue'
import PageCard from '@/components/PageCard.vue'
import RowActions from '@/components/RowActions.vue'
import { useCrud } from '@/composables/useCrud'
import { formatDate } from '@/utils/datetime'
import { required } from '@/utils/rules'

type Form = Pick<DeviceGroup, 'name' | 'description'>

const crud = useCrud<DeviceGroup, Form>({
  api: deviceGroupsApi,
  noun: 'device group',
  emptyForm: () => ({ name: '', description: '' }),
  toForm: (row) => ({ name: row.name, description: row.description }),
})

const columns: QTableColumn<DeviceGroup>[] = [
  { name: 'name', label: 'Name', field: 'name', align: 'left', sortable: true },
  { name: 'description', label: 'Description', field: 'description', align: 'left' },
  { name: 'created_at', label: 'Created', field: 'created_at', format: formatDate, align: 'left', sortable: true },
  { name: 'updated_at', label: 'Updated', field: 'updated_at', format: formatDate, align: 'left', sortable: true },
  { name: 'actions', label: 'Actions', field: 'id', align: 'right' },
]
</script>
