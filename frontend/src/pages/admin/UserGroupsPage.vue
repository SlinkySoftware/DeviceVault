<!-- SPDX-License-Identifier: GPL-3.0-or-later -->
<template>
  <PageCard
    title="User Groups"
    caption="Members get the union of their groups' permissions on device groups; global administrators hold everything"
  >
    <template #actions>
      <q-btn color="primary" icon="group_add" label="Add User Group" @click="crud.openCreate" />
    </template>

    <q-table
      flat
      :rows="crud.rows.value"
      :columns="columns"
      row-key="id"
      :loading="crud.loading.value"
      no-data-label="No user groups yet"
      class="admin-table"
    >
      <template #body-cell-name="props">
        <q-td :props="props">
          {{ props.row.name }}
          <q-badge v-if="props.row.is_global_admin" color="purple" class="q-ml-xs">Global admin</q-badge>
          <q-badge v-if="props.row.source === 'external'" color="blue" class="q-ml-xs">External</q-badge>
          <div v-if="props.row.description" class="text-caption text-muted">{{ props.row.description }}</div>
        </q-td>
      </template>
      <template #body-cell-grants="props">
        <q-td :props="props">
          <span v-if="props.row.is_global_admin" class="text-muted">Every device group</span>
          <div v-else class="row q-gutter-xs">
            <q-chip v-for="grant in props.row.grants" :key="grant.device_group" dense outline color="primary">
              {{ grant.device_group_name }} · {{ flagLetters(heldFlags(grant)) }}
            </q-chip>
            <span v-if="!props.row.grants.length" class="text-muted">No grants</span>
          </div>
        </q-td>
      </template>
      <template #body-cell-actions="props">
        <q-td :props="props">
          <RowActions
            :delete-disabled="props.row.is_builtin"
            delete-disabled-reason="The built-in Administrators group cannot be deleted"
            @edit="crud.openEdit(props.row)"
            @delete="crud.confirmRemove(props.row)"
          />
        </q-td>
      </template>
    </q-table>

    <FormDialog
      v-model="crud.dialogOpen.value"
      :title="crud.isEditing.value ? `Edit ${editing?.name ?? 'user group'}` : 'Add User Group'"
      :saving="crud.saving.value"
      width="820px"
      @submit="crud.save"
    >
      <q-input v-model.trim="crud.form.value.name" label="Name" outlined autofocus :rules="[required]" />
      <q-input v-model="crud.form.value.description" label="Description" outlined autogrow />
      <q-toggle
        v-model="crud.form.value.is_global_admin"
        label="Global administrator: every permission on every device group, and application administration"
        :disable="editing?.is_builtin"
      />
      <q-select
        v-model="crud.form.value.members"
        :options="users"
        option-value="id"
        option-label="username"
        emit-value
        map-options
        multiple
        use-chips
        use-input
        input-debounce="0"
        outlined
        label="Members"
        :readonly="editing?.source === 'external'"
        :hint="editing?.source === 'external' ? 'Filled by the identity provider at sign-in' : undefined"
        @filter="filterUsers"
      />

      <div v-if="!crud.form.value.is_global_admin">
        <div class="text-subtitle2 q-mb-sm">Device group permissions</div>
        <q-markup-table flat bordered dense>
          <thead>
            <tr>
              <th class="text-left">Device group</th>
              <th v-for="info in FLAGS" :key="info.flag" class="text-center">
                {{ info.label }}
                <q-tooltip>{{ info.description }}</q-tooltip>
              </th>
              <th />
            </tr>
          </thead>
          <tbody>
            <tr v-for="(grant, index) in crud.form.value.grants" :key="grant.device_group">
              <td>{{ groupName(grant.device_group) }}</td>
              <td v-for="info in FLAGS" :key="info.flag" class="text-center">
                <q-checkbox
                  :model-value="grant[info.flag]"
                  :disable="lockedFlags(grant).has(info.flag)"
                  dense
                  :aria-label="`${info.label} on ${groupName(grant.device_group)}`"
                  @update:model-value="(on: boolean) => toggle(index, info.flag, on)"
                />
              </td>
              <td class="text-right">
                <q-btn
                  flat
                  dense
                  round
                  icon="close"
                  color="negative"
                  :aria-label="`Remove ${groupName(grant.device_group)}`"
                  @click="crud.form.value.grants.splice(index, 1)"
                />
              </td>
            </tr>
            <tr v-if="!crud.form.value.grants.length">
              <td :colspan="FLAGS.length + 2" class="text-muted">No device groups: members of this group see nothing</td>
            </tr>
          </tbody>
        </q-markup-table>
        <q-select
          :model-value="null"
          :options="ungranted"
          option-value="id"
          option-label="name"
          emit-value
          map-options
          outlined
          dense
          label="Add a device group"
          class="q-mt-sm"
          style="max-width: 320px"
          @update:model-value="addGrant"
        />
      </div>
    </FormDialog>
  </PageCard>
</template>

<script setup lang="ts">
import type { QTableColumn } from 'quasar'
import { computed, onMounted, ref } from 'vue'

import { deviceGroupsApi, userGroupsApi, usersApi } from '@/api/endpoints'
import type { DeviceGroup, GrantFlag, Id, User, UserGroup, UserGroupWrite } from '@/api/types'
import FormDialog from '@/components/FormDialog.vue'
import PageCard from '@/components/PageCard.vue'
import RowActions from '@/components/RowActions.vue'
import { useCrud } from '@/composables/useCrud'
import { useNotify } from '@/composables/useNotify'
import { emptyFlags, FLAGS, flagLetters, heldFlags, lockedFlags, setFlag } from '@/utils/grants'
import { required } from '@/utils/rules'

const notify = useNotify()
const allUsers = ref<User[]>([])
const users = ref<User[]>([])
const deviceGroups = ref<DeviceGroup[]>([])
const editing = ref<UserGroup | null>(null)

const crud = useCrud<UserGroup, UserGroupWrite>({
  api: userGroupsApi,
  noun: 'user group',
  emptyForm: () => {
    editing.value = null
    return { name: '', description: '', is_global_admin: false, members: [], grants: [] }
  },
  toForm: (group) => {
    editing.value = group
    return {
      name: group.name,
      description: group.description,
      is_global_admin: group.is_global_admin,
      members: [...group.members],
      grants: group.grants.map((grant) => ({ ...grant })),
    }
  },
})

const columns: QTableColumn<UserGroup>[] = [
  { name: 'name', label: 'Name', field: 'name', align: 'left', sortable: true },
  { name: 'members', label: 'Members', field: (g) => g.members.length, align: 'center', sortable: true },
  { name: 'grants', label: 'Device groups (S B C D A)', field: (g) => g.grants.length, align: 'left' },
  { name: 'actions', label: 'Actions', field: 'id', align: 'right' },
]

const groupNames = computed(() => new Map(deviceGroups.value.map((group) => [group.id, group.name])))
const groupName = (id: Id) => groupNames.value.get(id) ?? `#${id}`
const ungranted = computed(() => {
  const granted = new Set(crud.form.value.grants.map((grant) => grant.device_group))
  return deviceGroups.value.filter((group) => !granted.has(group.id))
})

function addGrant(id: Id | null): void {
  if (id !== null) crud.form.value.grants.push({ device_group: id, ...emptyFlags() })
}

function toggle(index: number, flag: GrantFlag, on: boolean): void {
  const grant = crud.form.value.grants[index]
  if (grant) crud.form.value.grants[index] = { ...grant, ...setFlag(grant, flag, on) }
}

function filterUsers(needle: string, update: (fn: () => void) => void): void {
  update(() => {
    const term = needle.toLowerCase()
    users.value = allUsers.value.filter((user) => user.username.toLowerCase().includes(term))
  })
}

onMounted(async () => {
  try {
    ;[allUsers.value, deviceGroups.value] = await Promise.all([usersApi.list(), deviceGroupsApi.list()])
    users.value = allUsers.value
  } catch (error) {
    notify.error(error, 'Failed to load users and device groups')
  }
})
</script>
