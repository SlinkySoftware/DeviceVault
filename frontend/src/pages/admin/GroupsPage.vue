<!-- SPDX-License-Identifier: GPL-3.0-or-later -->
<template>
  <PageCard title="Groups" caption="User groups and the device group permissions their members inherit">
    <template #actions>
      <q-btn color="primary" icon="add" label="Add Group" @click="crud.openCreate" />
    </template>

    <q-table
      flat
      :rows="crud.rows.value"
      :columns="columns"
      row-key="id"
      :loading="crud.loading.value"
      no-data-label="No groups yet"
      class="admin-table"
    >
      <template #body-cell-members="props">
        <q-td :props="props"><q-badge color="primary" :label="props.row.users.length" /></q-td>
      </template>
      <template #body-cell-permissions="props">
        <q-td :props="props">
          <div class="row q-gutter-xs">
            <q-chip v-for="perm in props.row.device_group_permissions" :key="perm.id" dense outline color="primary">
              {{ perm.name }}
            </q-chip>
            <span v-if="props.row.device_group_permissions.length === 0" class="text-muted">No permissions</span>
          </div>
        </q-td>
      </template>
      <template #body-cell-actions="props">
        <q-td :props="props">
          <RowActions @edit="crud.openEdit(props.row)" @delete="crud.confirmRemove(props.row)" />
        </q-td>
      </template>
    </q-table>

    <FormDialog
      v-model="crud.dialogOpen.value"
      :title="crud.isEditing.value ? 'Edit Group' : 'Add Group'"
      :saving="crud.saving.value"
      width="600px"
      @submit="crud.save"
    >
      <q-input
        v-model.trim="crud.form.value.name"
        label="Group name"
        outlined
        autofocus
        :rules="[required, (v: string) => v.length <= 150 || 'At most 150 characters']"
      />
      <q-select
        v-model="crud.form.value.user_ids"
        :options="users"
        option-value="id"
        option-label="username"
        emit-value
        map-options
        multiple
        use-chips
        outlined
        label="Members"
      />
      <q-select
        v-model="crud.form.value.permission_ids"
        :options="permissions"
        option-value="id"
        option-label="name"
        emit-value
        map-options
        multiple
        use-chips
        outlined
        label="Device group permissions"
        hint="Members inherit these permissions"
      />
    </FormDialog>
  </PageCard>
</template>

<script setup lang="ts">
import type { QTableColumn } from 'quasar'
import { onMounted, ref } from 'vue'

import { groupsApi, permissionsApi, usersApi } from '@/api/endpoints'
import type { AuthGroup, AuthGroupWrite, DjangoPermission, User } from '@/api/types'
import FormDialog from '@/components/FormDialog.vue'
import PageCard from '@/components/PageCard.vue'
import RowActions from '@/components/RowActions.vue'
import { useCrud } from '@/composables/useCrud'
import { useNotify } from '@/composables/useNotify'
import { required } from '@/utils/rules'

const notify = useNotify()
const users = ref<User[]>([])
const permissions = ref<DjangoPermission[]>([])

const crud = useCrud<AuthGroup, AuthGroupWrite>({
  // Groups are edited with PATCH so membership changes are explicit.
  api: { ...groupsApi, update: (id, body) => groupsApi.patch(id, body) },
  noun: 'group',
  emptyForm: () => ({ name: '', user_ids: [], permission_ids: [] }),
  toForm: (group) => ({
    name: group.name,
    user_ids: group.users.map((u) => u.id),
    permission_ids: group.device_group_permissions.map((p) => p.id),
  }),
})

const columns: QTableColumn<AuthGroup>[] = [
  { name: 'name', label: 'Name', field: 'name', align: 'left', sortable: true },
  { name: 'members', label: 'Members', field: (g) => g.users.length, align: 'center', sortable: true },
  { name: 'permissions', label: 'Device Group Permissions', field: 'device_group_permissions', align: 'left' },
  { name: 'actions', label: 'Actions', field: 'id', align: 'right' },
]

onMounted(async () => {
  try {
    ;[users.value, permissions.value] = await Promise.all([usersApi.list(), permissionsApi.list()])
  } catch (error) {
    notify.error(error, 'Failed to load users and permissions')
  }
})
</script>
