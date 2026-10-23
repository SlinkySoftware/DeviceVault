<!-- SPDX-License-Identifier: GPL-3.0-or-later -->
<template>
  <PageCard title="Manufacturers" caption="Hardware vendors that devices can be tagged with">
    <template #actions>
      <q-btn color="primary" icon="add" label="Add Manufacturer" @click="crud.openCreate" />
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
      :title="crud.isEditing.value ? 'Edit Manufacturer' : 'Add Manufacturer'"
      :saving="crud.saving.value"
      @submit="crud.save"
    >
      <q-input v-model.trim="crud.form.value.name" label="Name" outlined autofocus :rules="[required]" />
    </FormDialog>
  </PageCard>
</template>

<script setup lang="ts">
import type { QTableColumn } from 'quasar'

import { manufacturersApi } from '@/api/endpoints'
import type { Manufacturer } from '@/api/types'
import FormDialog from '@/components/FormDialog.vue'
import PageCard from '@/components/PageCard.vue'
import RowActions from '@/components/RowActions.vue'
import { useCrud } from '@/composables/useCrud'
import { required } from '@/utils/rules'

const crud = useCrud<Manufacturer, Omit<Manufacturer, 'id'>>({
  api: manufacturersApi,
  noun: 'manufacturer',
  emptyForm: () => ({ name: '' }),
})

const columns: QTableColumn<Manufacturer>[] = [
  { name: 'name', label: 'Name', field: 'name', align: 'left', sortable: true },
  { name: 'actions', label: 'Actions', field: 'id', align: 'right' },
]
</script>
