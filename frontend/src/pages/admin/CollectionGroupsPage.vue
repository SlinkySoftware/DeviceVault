<!-- SPDX-License-Identifier: GPL-3.0-or-later -->
<template>
  <PageCard title="Collection Groups" caption="Each group is a RabbitMQ queue that a set of collectors consumes">
    <template #actions>
      <q-btn color="primary" icon="add" label="Add Collection Group" @click="crud.openCreate" />
    </template>

    <q-table flat :rows="crud.rows.value" :columns="columns" row-key="id" :loading="crud.loading.value" class="admin-table">
      <template #body-cell-queue="props">
        <q-td :props="props">
          <code>{{ queueName(props.row.rabbitmq_queue_id) }}</code>
        </q-td>
      </template>
      <template #body-cell-device_count="props">
        <q-td :props="props"><q-badge color="info" :label="props.row.device_count" /></q-td>
      </template>
      <template #body-cell-actions="props">
        <q-td :props="props">
          <RowActions
            :delete-disabled="props.row.device_count > 0"
            delete-disabled-reason="Move its devices to another group first"
            @edit="crud.openEdit(props.row)"
            @delete="crud.confirmRemove(props.row)"
          />
        </q-td>
      </template>
    </q-table>

    <FormDialog
      v-model="crud.dialogOpen.value"
      :title="crud.isEditing.value ? 'Edit Collection Group' : 'Add Collection Group'"
      :saving="crud.saving.value"
      @submit="crud.save"
    >
      <q-input v-model.trim="crud.form.value.name" label="Name" outlined autofocus :rules="[required]" />
      <q-input v-model="crud.form.value.description" label="Description" type="textarea" autogrow outlined />
      <q-input
        v-model.trim="crud.form.value.rabbitmq_queue_id"
        label="Queue ID"
        outlined
        :hint="`Collectors consume ${queueName(crud.form.value.rabbitmq_queue_id || '<id>')}`"
        :rules="[required, queueId]"
      />
    </FormDialog>
  </PageCard>
</template>

<script setup lang="ts">
import type { QTableColumn } from 'quasar'

import { collectionGroupsApi } from '@/api/endpoints'
import type { CollectionGroup } from '@/api/types'
import FormDialog from '@/components/FormDialog.vue'
import PageCard from '@/components/PageCard.vue'
import RowActions from '@/components/RowActions.vue'
import { useCrud } from '@/composables/useCrud'
import { required } from '@/utils/rules'

type Form = Pick<CollectionGroup, 'name' | 'description' | 'rabbitmq_queue_id'>

const queueName = (id: string) => `collector.group.${id}`
const queueId = (value: string) => /^[\w.-]+$/.test(value) || 'Letters, digits, ".", "-" and "_" only'

const crud = useCrud<CollectionGroup, Form>({
  api: collectionGroupsApi,
  noun: 'collection group',
  emptyForm: () => ({ name: '', description: '', rabbitmq_queue_id: '' }),
  toForm: (row) => ({ name: row.name, description: row.description, rabbitmq_queue_id: row.rabbitmq_queue_id }),
})

const columns: QTableColumn<CollectionGroup>[] = [
  { name: 'name', label: 'Name', field: 'name', align: 'left', sortable: true },
  { name: 'description', label: 'Description', field: 'description', align: 'left' },
  { name: 'queue', label: 'Queue', field: 'rabbitmq_queue_id', align: 'left' },
  { name: 'device_count', label: 'Devices', field: 'device_count', align: 'center', sortable: true },
  { name: 'actions', label: 'Actions', field: 'id', align: 'right' },
]
</script>
