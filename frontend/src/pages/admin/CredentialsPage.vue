<!-- SPDX-License-Identifier: GPL-3.0-or-later -->
<template>
  <PageCard title="Credentials" caption="Authentication used by collectors to connect to devices">
    <template #actions>
      <q-btn color="primary" icon="add" label="Add Credential" @click="crud.openCreate" />
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
      :title="crud.isEditing.value ? 'Edit Credential' : 'Add Credential'"
      :saving="crud.saving.value"
      width="600px"
      @submit="crud.save"
    >
      <q-input v-model.trim="crud.form.value.name" label="Name" outlined autofocus :rules="[required]" />
      <q-select
        v-model="crud.form.value.credential_type"
        :options="types"
        option-value="id"
        option-label="name"
        emit-value
        map-options
        label="Credential type"
        outlined
        :rules="[required]"
      />
      <JsonEditor
        v-model="crud.form.value.data"
        label="Credential data (JSON)"
        hint='For local credentials, e.g. {"username": "backup", "password": "..."}'
      />
    </FormDialog>
  </PageCard>
</template>

<script setup lang="ts">
import type { QTableColumn } from 'quasar'
import { computed, onMounted, ref } from 'vue'

import { credentialsApi, credentialTypesApi } from '@/api/endpoints'
import type { Credential, CredentialType, CredentialWrite, Id } from '@/api/types'
import FormDialog from '@/components/FormDialog.vue'
import JsonEditor from '@/components/JsonEditor.vue'
import PageCard from '@/components/PageCard.vue'
import RowActions from '@/components/RowActions.vue'
import { useCrud } from '@/composables/useCrud'
import { useNotify } from '@/composables/useNotify'
import { required } from '@/utils/rules'

const notify = useNotify()
const types = ref<CredentialType[]>([])
const typeNames = computed(() => new Map(types.value.map((t) => [t.id, t.name])))

const crud = useCrud<Credential, CredentialWrite>({
  api: credentialsApi,
  noun: 'credential',
  emptyForm: () => ({ name: '', credential_type: null, data: {} }),
  toForm: (row) => ({ name: row.name, credential_type: row.credential_type, data: { ...(row.data ?? {}) } }),
})

const columns: QTableColumn<Credential>[] = [
  { name: 'name', label: 'Name', field: 'name', align: 'left', sortable: true },
  {
    name: 'type',
    label: 'Type',
    field: 'credential_type',
    format: (id: Id) => typeNames.value.get(id) ?? `#${id}`,
    align: 'left',
    sortable: true,
  },
  { name: 'actions', label: 'Actions', field: 'id', align: 'right' },
]

onMounted(async () => {
  try {
    types.value = await credentialTypesApi.list()
  } catch (error) {
    notify.error(error, 'Failed to load credential types')
  }
})
</script>
