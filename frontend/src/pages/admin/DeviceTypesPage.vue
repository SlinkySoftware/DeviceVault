<!-- SPDX-License-Identifier: GPL-3.0-or-later -->
<template>
  <PageCard title="Device Types" caption="Device categories and their icons">
    <template #actions>
      <q-btn color="primary" icon="add" label="Add Device Type" @click="crud.openCreate" />
    </template>

    <q-table flat :rows="crud.rows.value" :columns="columns" row-key="id" :loading="crud.loading.value" class="admin-table">
      <template #body-cell-icon="props">
        <q-td :props="props"><q-icon :name="props.row.icon || 'router'" size="md" color="primary" /></q-td>
      </template>
      <template #body-cell-actions="props">
        <q-td :props="props">
          <RowActions @edit="crud.openEdit(props.row)" @delete="crud.confirmRemove(props.row)" />
        </q-td>
      </template>
    </q-table>

    <FormDialog
      v-model="crud.dialogOpen.value"
      :title="crud.isEditing.value ? 'Edit Device Type' : 'Add Device Type'"
      :saving="crud.saving.value"
      @submit="crud.save"
    >
      <q-input v-model.trim="crud.form.value.name" label="Name" outlined autofocus :rules="[required]" />
      <q-select v-model="crud.form.value.icon" :options="ICONS" label="Icon" outlined>
        <template #prepend><q-icon :name="crud.form.value.icon || 'router'" /></template>
        <template #option="scope">
          <q-item v-bind="scope.itemProps">
            <q-item-section avatar><q-icon :name="scope.opt" /></q-item-section>
            <q-item-section>{{ scope.opt }}</q-item-section>
          </q-item>
        </template>
      </q-select>
    </FormDialog>
  </PageCard>
</template>

<script setup lang="ts">
import type { QTableColumn } from 'quasar'

import { deviceTypesApi } from '@/api/endpoints'
import type { DeviceType } from '@/api/types'
import FormDialog from '@/components/FormDialog.vue'
import PageCard from '@/components/PageCard.vue'
import RowActions from '@/components/RowActions.vue'
import { useCrud } from '@/composables/useCrud'
import { required } from '@/utils/rules'

const ICONS = ['router', 'dns', 'security', 'shield', 'wifi', 'cloud', 'computer', 'storage', 'vpn_lock', 'hub', 'lan']

const crud = useCrud<DeviceType, Omit<DeviceType, 'id'>>({
  api: deviceTypesApi,
  noun: 'device type',
  emptyForm: () => ({ name: '', icon: 'router' }),
})

const columns: QTableColumn<DeviceType>[] = [
  { name: 'icon', label: 'Icon', field: 'icon', align: 'center', style: 'width: 80px' },
  { name: 'name', label: 'Name', field: 'name', align: 'left', sortable: true },
  { name: 'actions', label: 'Actions', field: 'id', align: 'right' },
]
</script>
