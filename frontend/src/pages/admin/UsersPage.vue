<!-- SPDX-License-Identifier: GPL-3.0-or-later -->
<template>
  <PageCard title="Users">
    <template #caption>
      Local and externally provisioned users
      <span v-if="!localAuthEnabled" class="text-orange">· local authentication is disabled</span>
    </template>
    <template #actions>
      <q-btn color="primary" icon="person_add" label="Add User" :disable="!localAuthEnabled" @click="openCreate">
        <q-tooltip v-if="!localAuthEnabled">Local accounts can only be created when local authentication is enabled</q-tooltip>
      </q-btn>
    </template>

    <q-table flat :rows="users" :columns="columns" row-key="id" :loading="loading" class="admin-table">
      <template #body-cell-source="props">
        <q-td :props="props">
          <q-badge :color="props.row.is_jit ? 'blue' : 'grey'">{{ props.row.is_jit ? 'Provisioned' : 'Local' }}</q-badge>
          <q-badge v-if="props.row.is_superuser" color="purple" class="q-ml-xs">Superuser</q-badge>
          <q-badge v-else-if="props.row.is_staff" color="teal" class="q-ml-xs">Admin</q-badge>
        </q-td>
      </template>
      <template #body-cell-actions="props">
        <q-td :props="props" class="q-gutter-xs">
          <q-btn
            dense
            color="primary"
            icon="edit"
            label="Edit"
            :disable="props.row.is_jit"
            @click="openEdit(props.row)"
          >
            <q-tooltip v-if="props.row.is_jit">Managed by the external identity provider</q-tooltip>
          </q-btn>
          <q-btn dense color="primary" icon="security" label="Roles" @click="openRoles(props.row)" />
        </q-td>
      </template>
    </q-table>

    <FormDialog v-model="createDialog" title="Add User" :saving="saving" submit-label="Create" @submit="create">
      <q-input v-model.trim="newUser.username" label="Username" outlined autofocus :rules="[required]" />
      <q-input v-model.trim="newUser.email" label="Email" type="email" outlined />
      <q-input v-model.trim="newUser.first_name" label="First name" outlined />
      <q-input v-model.trim="newUser.last_name" label="Last name" outlined />
      <q-input
        v-model="newUser.password"
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
        :rules="[required, (v: string) => v === newUser.password || 'Passwords do not match']"
      />
    </FormDialog>

    <FormDialog v-model="editDialog" :title="`Edit ${editing?.username ?? ''}`" :saving="saving" @submit="update">
      <q-input v-model.trim="details.email" label="Email" type="email" outlined />
      <q-input v-model.trim="details.first_name" label="First name" outlined />
      <q-input v-model.trim="details.last_name" label="Last name" outlined />
    </FormDialog>

    <UserRolesDialog v-model="rolesDialog" :user="rolesUser" />
  </PageCard>
</template>

<script setup lang="ts">
import type { QTableColumn } from 'quasar'
import { onMounted, reactive, ref } from 'vue'

import { authApi, usersApi } from '@/api/endpoints'
import type { User, UserCreate, UserDetails } from '@/api/types'
import FormDialog from '@/components/FormDialog.vue'
import PageCard from '@/components/PageCard.vue'
import UserRolesDialog from '@/components/UserRolesDialog.vue'
import { useNotify } from '@/composables/useNotify'
import { required } from '@/utils/rules'

const notify = useNotify()
const users = ref<User[]>([])
const loading = ref(false)
const saving = ref(false)
const localAuthEnabled = ref(false)

const columns: QTableColumn<User>[] = [
  { name: 'username', label: 'Username', field: 'username', align: 'left', sortable: true },
  { name: 'name', label: 'Name', field: (u) => `${u.first_name} ${u.last_name}`.trim(), align: 'left', sortable: true },
  { name: 'email', label: 'Email', field: 'email', align: 'left', sortable: true },
  { name: 'source', label: 'Source', field: 'is_jit', align: 'left' },
  { name: 'actions', label: 'Actions', field: 'id', align: 'right' },
]

async function load(): Promise<void> {
  loading.value = true
  try {
    users.value = await usersApi.list()
  } catch (error) {
    notify.error(error, 'Failed to load users')
  } finally {
    loading.value = false
  }
}

const createDialog = ref(false)
const newUser = reactive<UserCreate>({ username: '', email: '', first_name: '', last_name: '', password: '' })
const confirmPassword = ref('')

function openCreate(): void {
  Object.assign(newUser, { username: '', email: '', first_name: '', last_name: '', password: '' })
  confirmPassword.value = ''
  createDialog.value = true
}

async function create(): Promise<void> {
  saving.value = true
  try {
    await usersApi.create({ ...newUser })
    notify.success(`User ${newUser.username} created`)
    createDialog.value = false
    await load()
  } catch (error) {
    notify.error(error, 'Failed to create user')
  } finally {
    saving.value = false
  }
}

const editDialog = ref(false)
const editing = ref<User | null>(null)
const details = reactive<UserDetails>({ email: '', first_name: '', last_name: '' })

function openEdit(user: User): void {
  editing.value = user
  Object.assign(details, { email: user.email, first_name: user.first_name, last_name: user.last_name })
  editDialog.value = true
}

async function update(): Promise<void> {
  if (!editing.value) return
  saving.value = true
  try {
    await usersApi.updateDetails(editing.value.id, { ...details })
    notify.success('User updated')
    editDialog.value = false
    await load()
  } catch (error) {
    notify.error(error, 'Failed to update user')
  } finally {
    saving.value = false
  }
}

const rolesDialog = ref(false)
const rolesUser = ref<User | null>(null)

function openRoles(user: User): void {
  rolesUser.value = user
  rolesDialog.value = true
}

onMounted(async () => {
  void load()
  try {
    const config = await authApi.config()
    localAuthEnabled.value = config.local_enabled
  } catch {
    localAuthEnabled.value = false
  }
})
</script>
