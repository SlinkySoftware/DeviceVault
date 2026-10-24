<!-- SPDX-License-Identifier: GPL-3.0-or-later -->
<template>
  <PageCard title="Users">
    <template #caption>
      Accounts, their user groups and whether they can sign in
      <span v-if="!localAuthEnabled" class="text-orange">· local authentication is disabled</span>
    </template>
    <template #actions>
      <q-btn color="primary" icon="person_add" label="Add User" :disable="!localAuthEnabled" @click="crud.openCreate">
        <q-tooltip v-if="!localAuthEnabled">Local accounts can only be created when local authentication is enabled</q-tooltip>
      </q-btn>
    </template>

    <q-input v-model="filter" dense outlined clearable debounce="200" label="Filter" class="q-mb-md" style="max-width: 320px">
      <template #prepend><q-icon name="search" /></template>
    </q-input>

    <q-table
      flat
      :rows="crud.rows.value"
      :columns="columns"
      :filter="filter"
      row-key="id"
      :loading="crud.loading.value"
      :pagination="{ rowsPerPage: 25, sortBy: 'username' }"
      class="admin-table"
    >
      <template #body-cell-username="props">
        <q-td :props="props">
          {{ props.row.username }}
          <q-badge v-if="props.row.id === auth.user?.id" color="grey" class="q-ml-xs">You</q-badge>
        </q-td>
      </template>
      <template #body-cell-status="props">
        <q-td :props="props">
          <q-badge :color="props.row.is_active ? 'positive' : 'grey'">{{ props.row.is_active ? 'Active' : 'Disabled' }}</q-badge>
          <q-badge :color="props.row.source === 'local' ? 'blue-grey' : 'blue'" class="q-ml-xs">
            {{ props.row.source === 'local' ? 'Local' : props.row.providers.join(', ') || 'External' }}
          </q-badge>
          <q-badge v-if="props.row.is_global_admin" color="purple" class="q-ml-xs">Global admin</q-badge>
          <q-badge v-if="props.row.break_glass" color="deep-orange" class="q-ml-xs">
            Break-glass
            <q-tooltip>Can sign in even when local authentication is disabled</q-tooltip>
          </q-badge>
        </q-td>
      </template>
      <template #body-cell-groups="props">
        <q-td :props="props">
          <div class="row q-gutter-xs">
            <q-chip v-for="name in props.row.group_names" :key="name" dense outline color="primary">{{ name }}</q-chip>
            <span v-if="!props.row.group_names.length" class="text-muted">No groups: no access</span>
          </div>
        </q-td>
      </template>
      <template #body-cell-actions="props">
        <q-td :props="props">
          <RowActions
            :delete-disabled="props.row.id === auth.user?.id"
            delete-disabled-reason="You cannot delete your own account"
            @edit="crud.openEdit(props.row)"
            @delete="crud.confirmRemove(props.row)"
          >
            <q-btn
              dense
              color="primary"
              icon="password"
              label="Password"
              :disable="props.row.source !== 'local'"
              @click="openPassword(props.row)"
            >
              <q-tooltip v-if="props.row.source !== 'local'">Managed by the identity provider</q-tooltip>
            </q-btn>
          </RowActions>
        </q-td>
      </template>
    </q-table>

    <FormDialog
      v-model="crud.dialogOpen.value"
      :title="crud.isEditing.value ? `Edit ${editing?.username ?? 'user'}` : 'Add User'"
      :saving="crud.saving.value"
      :submit-label="crud.isEditing.value ? 'Save' : 'Create'"
      @submit="crud.save"
    >
      <q-input
        v-if="!crud.isEditing.value"
        v-model.trim="crud.form.value.username"
        label="Username"
        outlined
        autofocus
        :rules="[required]"
      />
      <q-input
        v-model.trim="crud.form.value.email"
        label="Email"
        type="email"
        outlined
        :readonly="editingExternal"
      />
      <q-input v-model.trim="crud.form.value.first_name" label="First name" outlined :readonly="editingExternal" />
      <q-input v-model.trim="crud.form.value.last_name" label="Last name" outlined :readonly="editingExternal" />
      <template v-if="!crud.isEditing.value">
        <q-input
          v-model="crud.form.value.password"
          label="Password"
          type="password"
          autocomplete="new-password"
          outlined
          :rules="[required]"
        />
        <q-input
          v-model="confirmPassword"
          label="Confirm password"
          type="password"
          autocomplete="new-password"
          outlined
          :rules="[required, (v: string) => v === crud.form.value.password || 'Passwords do not match']"
        />
      </template>
      <q-select
        v-model="crud.form.value.groups"
        :options="internalGroups"
        option-value="id"
        option-label="name"
        emit-value
        map-options
        multiple
        use-chips
        outlined
        label="User groups"
        hint="Access comes only from user groups"
      />
      <q-toggle
        v-model="crud.form.value.is_active"
        label="Can sign in"
        :disable="editing?.id === auth.user?.id"
      />
      <q-toggle
        v-if="!editingExternal"
        v-model="crud.form.value.break_glass"
        label="Break-glass: may sign in even when local authentication is disabled"
      />
    </FormDialog>

    <FormDialog
      v-model="passwordDialog"
      :title="`Set password · ${passwordUser?.username ?? ''}`"
      :saving="savingPassword"
      @submit="setPassword"
    >
      <q-input
        v-model="newPassword"
        label="New password"
        type="password"
        autocomplete="new-password"
        outlined
        autofocus
        :rules="[required]"
        hint="Signs the user out everywhere"
      />
      <q-input
        v-model="confirmNewPassword"
        label="Confirm password"
        type="password"
        autocomplete="new-password"
        outlined
        :rules="[required, (v: string) => v === newPassword || 'Passwords do not match']"
      />
    </FormDialog>
  </PageCard>
</template>

<script setup lang="ts">
import type { QTableColumn } from 'quasar'
import { computed, onMounted, ref } from 'vue'

import { authApi, userGroupsApi, usersApi } from '@/api/endpoints'
import type { User, UserCreate, UserGroup } from '@/api/types'
import FormDialog from '@/components/FormDialog.vue'
import PageCard from '@/components/PageCard.vue'
import RowActions from '@/components/RowActions.vue'
import { useCrud } from '@/composables/useCrud'
import { useNotify } from '@/composables/useNotify'
import { useAuthStore } from '@/stores/auth'
import { formatDateTime } from '@/utils/datetime'
import { required } from '@/utils/rules'

const auth = useAuthStore()
const notify = useNotify()
const groups = ref<UserGroup[]>([])
const localAuthEnabled = ref(true)
const filter = ref('')
const confirmPassword = ref('')
const editing = ref<User | null>(null)

// External groups are filled by their identity provider.
const internalGroups = computed(() => groups.value.filter((group) => group.source === 'internal'))
const editingExternal = computed(() => editing.value?.source === 'external')

const crud = useCrud<User, UserCreate>({
  api: {
    list: usersApi.list,
    create: usersApi.create,
    remove: usersApi.remove,
    update: (id, form) => {
      const { email, first_name, last_name, is_active, groups, break_glass } = form
      // External users' profiles come from their provider.
      const profile = editing.value?.source === 'external' ? {} : { email, first_name, last_name, break_glass }
      return usersApi.update(Number(id), { ...profile, is_active, groups })
    },
  },
  noun: 'user',
  describe: (user) => user.username,
  emptyForm: () => {
    editing.value = null
    confirmPassword.value = ''
    return {
      username: '',
      email: '',
      first_name: '',
      last_name: '',
      password: '',
      is_active: true,
      groups: [],
      break_glass: false,
    }
  },
  toForm: (user) => {
    editing.value = user
    return { ...user, password: '' }
  },
})

const columns: QTableColumn<User>[] = [
  { name: 'username', label: 'Username', field: 'username', align: 'left', sortable: true },
  { name: 'name', label: 'Name', field: (u) => `${u.first_name} ${u.last_name}`.trim(), align: 'left', sortable: true },
  { name: 'email', label: 'Email', field: 'email', align: 'left', sortable: true },
  { name: 'status', label: 'Status', field: 'is_active', align: 'left' },
  { name: 'groups', label: 'User groups', field: (u) => u.group_names.join(' '), align: 'left' },
  {
    name: 'last_login',
    label: 'Last sign-in',
    field: 'last_login',
    format: (value: string | null) => (value ? formatDateTime(value) : 'Never'),
    align: 'left',
    sortable: true,
  },
  { name: 'actions', label: 'Actions', field: 'id', align: 'right' },
]

const passwordDialog = ref(false)
const passwordUser = ref<User | null>(null)
const newPassword = ref('')
const confirmNewPassword = ref('')
const savingPassword = ref(false)

function openPassword(user: User): void {
  passwordUser.value = user
  newPassword.value = ''
  confirmNewPassword.value = ''
  passwordDialog.value = true
}

async function setPassword(): Promise<void> {
  if (!passwordUser.value) return
  savingPassword.value = true
  try {
    await usersApi.setPassword(passwordUser.value.id, newPassword.value)
    notify.success(`Password of ${passwordUser.value.username} changed`)
    passwordDialog.value = false
  } catch (error) {
    notify.error(error, 'Failed to set the password')
  } finally {
    savingPassword.value = false
  }
}

onMounted(async () => {
  try {
    const [groupList, config] = await Promise.all([userGroupsApi.list(), authApi.config()])
    groups.value = groupList
    localAuthEnabled.value = config.local_enabled
  } catch (error) {
    notify.error(error, 'Failed to load user groups')
  }
})
</script>
