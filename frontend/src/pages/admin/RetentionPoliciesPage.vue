<!-- SPDX-License-Identifier: GPL-3.0-or-later -->
<template>
  <PageCard title="Retention Policies" caption="How long backups are kept before cleanup (any limit that is set applies)">
    <template #actions>
      <q-btn color="primary" icon="add" label="Add Policy" @click="crud.openCreate" />
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
      :title="crud.isEditing.value ? 'Edit Retention Policy' : 'Add Retention Policy'"
      :saving="crud.saving.value"
      @submit="crud.save"
    >
      <q-input v-model.trim="crud.form.value.name" label="Name" outlined autofocus :rules="[required]" />
      <q-input
        v-model.number="crud.form.value.max_backups"
        type="number"
        label="Keep at most N backups"
        outlined
        clearable
        :rules="[optionalNonNegativeInteger]"
      />
      <q-input
        v-model.number="crud.form.value.max_days"
        type="number"
        label="Delete backups older than N days"
        outlined
        clearable
        :rules="[optionalNonNegativeInteger]"
      />
      <q-input
        v-model.number="crud.form.value.max_size_bytes"
        type="number"
        label="Total size limit (bytes)"
        :hint="formatBytes(crud.form.value.max_size_bytes) || undefined"
        outlined
        clearable
        :rules="[optionalNonNegativeInteger]"
      />
    </FormDialog>
  </PageCard>
</template>

<script setup lang="ts">
import type { QTableColumn } from 'quasar'

import { retentionPoliciesApi } from '@/api/endpoints'
import type { RetentionPolicy } from '@/api/types'
import FormDialog from '@/components/FormDialog.vue'
import PageCard from '@/components/PageCard.vue'
import RowActions from '@/components/RowActions.vue'
import { useCrud } from '@/composables/useCrud'
import { formatBytes } from '@/utils/format'
import { optionalNonNegativeInteger, required } from '@/utils/rules'

type Form = Omit<RetentionPolicy, 'id'>

// Cleared number inputs yield '' or null; the API wants null.
const toNullable = (value: number | string | null) => (value === '' || value === null ? null : Number(value))

const crud = useCrud<RetentionPolicy, Form>({
  api: {
    ...retentionPoliciesApi,
    create: (form) => retentionPoliciesApi.create(normalise(form)),
    update: (id, form) => retentionPoliciesApi.update(id, normalise(form)),
  },
  noun: 'retention policy',
  emptyForm: () => ({ name: '', max_backups: null, max_days: null, max_size_bytes: null }),
})

function normalise(form: Form): Form {
  return {
    name: form.name,
    max_backups: toNullable(form.max_backups),
    max_days: toNullable(form.max_days),
    max_size_bytes: toNullable(form.max_size_bytes),
  }
}

const orNone = (value: number | null) => (value === null ? '—' : String(value))

const columns: QTableColumn<RetentionPolicy>[] = [
  { name: 'name', label: 'Name', field: 'name', align: 'left', sortable: true },
  { name: 'max_backups', label: 'Max Backups', field: 'max_backups', format: orNone, align: 'left' },
  { name: 'max_days', label: 'Max Days', field: 'max_days', format: orNone, align: 'left' },
  {
    name: 'max_size',
    label: 'Max Size',
    field: 'max_size_bytes',
    format: (value: number | null) => formatBytes(value) || '—',
    align: 'left',
  },
  { name: 'actions', label: 'Actions', field: 'id', align: 'right' },
]
</script>
