<!-- SPDX-License-Identifier: GPL-3.0-or-later -->
<template>
  <PageCard
    title="Credentials"
    caption="Authentication collectors use to connect to devices: global ones, and those owned by a device group"
  >
    <template #actions>
      <q-btn color="primary" icon="add" label="Add Credential" @click="crud.openCreate" />
    </template>

    <q-table flat :rows="crud.rows.value" :columns="columns" row-key="id" :loading="crud.loading.value" class="admin-table">
      <template #body-cell-owner="props">
        <q-td :props="props">
          <q-badge v-if="props.row.device_group === null" color="grey" outline>Global</q-badge>
          <q-badge v-else color="info" outline>{{ props.row.device_group_name }}</q-badge>
        </q-td>
      </template>
      <template #body-cell-actions="props">
        <q-td :props="props">
          <RowActions
            :edit-disabled="!mayManage(props.row)"
            :delete-disabled="!mayManage(props.row)"
            edit-disabled-reason="Global credentials are managed by global administrators"
            delete-disabled-reason="Global credentials are managed by global administrators"
            @edit="crud.openEdit(props.row)"
            @delete="crud.confirmRemove(props.row)"
          />
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
      <q-select
        v-model="crud.form.value.device_group"
        :options="ownerOptions"
        option-value="id"
        option-label="name"
        emit-value
        map-options
        outlined
        label="Owner"
        hint="A global credential is usable by every device group; an owned one only by its group's devices"
      />
      <JsonEditor
        v-model="data"
        label="Credential data (JSON)"
        :hint="crud.isEditing.value ? EDIT_HINT : CREATE_HINT"
      />
    </FormDialog>
  </PageCard>
</template>

<script setup lang="ts">
import type { QTableColumn } from 'quasar'
import { computed, onMounted, ref } from 'vue'

import { credentialsApi, credentialTypesApi, deviceGroupsApi } from '@/api/endpoints'
import type { Credential, CredentialType, CredentialWrite, DeviceGroup, Id, JsonObject } from '@/api/types'
import FormDialog from '@/components/FormDialog.vue'
import JsonEditor from '@/components/JsonEditor.vue'
import PageCard from '@/components/PageCard.vue'
import RowActions from '@/components/RowActions.vue'
import { useCrud } from '@/composables/useCrud'
import { useNotify } from '@/composables/useNotify'
import { useAuthStore } from '@/stores/auth'
import { required } from '@/utils/rules'

const CREATE_HINT = 'For local credentials, e.g. {"username": "backup", "password": "..."}'
const EDIT_HINT = 'Stored values are never shown: a key left null keeps its value'

const auth = useAuthStore()
const notify = useNotify()
const types = ref<CredentialType[]>([])
const deviceGroups = ref<DeviceGroup[]>([])
const typeNames = computed(() => new Map(types.value.map((t) => [t.id, t.name])))
// The JSON editor's contents; sent only when it differs from the placeholder.
const data = ref<JsonObject>({})
let placeholder = '{}'

const mayManage = (row: Credential) => auth.can('admin', row.device_group)
// Global administrators may own credentials by any group (or none); group admins by their groups.
const ownerOptions = computed(() => [
  ...(auth.isGlobalAdmin ? [{ id: null, name: 'Global (every device group)' }] : []),
  ...deviceGroups.value.filter((group) => auth.can('admin', group.id)),
])

function withData(form: CredentialWrite): CredentialWrite {
  return JSON.stringify(data.value) === placeholder ? form : { ...form, data: data.value }
}

const crud = useCrud<Credential, CredentialWrite>({
  api: {
    list: credentialsApi.list,
    remove: credentialsApi.remove,
    create: (form) => credentialsApi.create({ ...form, data: data.value }),
    update: (id, form) => credentialsApi.patch(id, withData(form)),
  },
  noun: 'credential',
  emptyForm: () => {
    data.value = {}
    placeholder = '{}'
    return { name: '', credential_type: null, device_group: auth.isGlobalAdmin ? null : (ownerOptions.value[0]?.id ?? null) }
  },
  toForm: (row) => {
    // Secrets are write-only: show which keys are set, as nulls that keep their values.
    data.value = Object.fromEntries(row.data_keys.map((key) => [key, null]))
    placeholder = JSON.stringify(data.value)
    return { name: row.name, credential_type: row.credential_type, device_group: row.device_group }
  },
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
  { name: 'owner', label: 'Owner', field: (row) => row.device_group_name ?? '', align: 'left', sortable: true },
  {
    name: 'keys',
    label: 'Set',
    field: 'data_keys',
    format: (keys: string[]) => keys.join(', '),
    align: 'left',
  },
  { name: 'actions', label: 'Actions', field: 'id', align: 'right' },
]

onMounted(async () => {
  try {
    ;[types.value, deviceGroups.value] = await Promise.all([credentialTypesApi.list(), deviceGroupsApi.list()])
  } catch (error) {
    notify.error(error, 'Failed to load credential types and device groups')
  }
})
</script>
