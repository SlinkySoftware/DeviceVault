<!-- SPDX-License-Identifier: GPL-3.0-or-later -->
<template>
  <PageCard title="Service Accounts">
    <template #caption>
      Machine accounts that never sign in and exist to own API tokens, such as a monitoring system's. Their access
      comes from their user groups, which cannot be global-administrator groups.
    </template>
    <template #actions>
      <q-btn color="primary" icon="smart_toy" label="Add Service Account" @click="crud.openCreate" />
    </template>

    <q-table
      flat
      :rows="crud.rows.value"
      :columns="columns"
      row-key="id"
      :loading="crud.loading.value"
      :pagination="{ rowsPerPage: 25, sortBy: 'username' }"
      class="admin-table"
    >
      <template #body-cell-status="props">
        <q-td :props="props">
          <q-badge :color="props.row.is_active ? 'positive' : 'grey'">{{ props.row.is_active ? 'Active' : 'Disabled' }}</q-badge>
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
          <RowActions @edit="crud.openEdit(props.row)" @delete="crud.confirmRemove(props.row, 'Its tokens stop working.')">
            <q-btn dense color="primary" icon="key" label="Tokens" @click="openTokens(props.row)" />
          </RowActions>
        </q-td>
      </template>
    </q-table>

    <div class="text-h6 q-mt-lg">All API tokens</div>
    <div class="text-caption text-grey q-mb-sm">Every token that has not been revoked, of people and service accounts</div>
    <q-table
      flat
      dense
      :rows="allTokens"
      :columns="tokenColumns"
      row-key="id"
      :loading="loadingTokens"
      :pagination="{ rowsPerPage: 25 }"
      no-data-label="No tokens"
    >
      <template #body-cell-actions="props">
        <q-td :props="props">
          <q-btn dense color="negative" icon="block" label="Revoke" @click="confirmRevoke(props.row)" />
        </q-td>
      </template>
    </q-table>

    <FormDialog
      v-model="crud.dialogOpen.value"
      :title="crud.isEditing.value ? `Edit ${crud.form.value.username}` : 'Add Service Account'"
      :saving="crud.saving.value"
      :submit-label="crud.isEditing.value ? 'Save' : 'Create'"
      @submit="crud.save"
    >
      <q-input
        v-model.trim="crud.form.value.username"
        label="Name"
        outlined
        autofocus
        :readonly="crud.isEditing.value"
        :rules="[required]"
        hint="e.g. zabbix"
      />
      <q-input v-model.trim="crud.form.value.description" label="Description" outlined maxlength="200" />
      <q-select
        v-model="crud.form.value.groups"
        :options="eligibleGroups"
        option-value="id"
        option-label="name"
        emit-value
        map-options
        multiple
        use-chips
        outlined
        label="User groups"
        hint="Grant view on the device groups it should see; global-administrator groups are not offered"
      />
      <q-toggle v-model="crud.form.value.is_active" label="Active (its tokens work)" />
    </FormDialog>

    <q-dialog v-model="tokensOpen">
      <q-card style="width: 960px; max-width: 95vw">
        <q-card-section class="row items-center q-pb-none">
          <div class="text-h6">Tokens · {{ tokensFor?.username }}</div>
          <q-space />
          <q-btn v-close-popup icon="close" flat round dense aria-label="Close" />
        </q-card-section>
        <q-card-section v-if="tokensFor">
          <ApiTokensPanel :api="serviceAccountsApi.tokens(tokensFor.id)" :owner-label="`${tokensFor.username}'s`" allow-platform />
        </q-card-section>
      </q-card>
    </q-dialog>
  </PageCard>
</template>

<script setup lang="ts">
import { useQuasar, type QTableColumn } from 'quasar'
import { computed, onMounted, ref, watch } from 'vue'

import { adminTokensApi, serviceAccountsApi, userGroupsApi } from '@/api/endpoints'
import type { ApiToken, ServiceAccount, ServiceAccountWrite, UserGroup } from '@/api/types'
import ApiTokensPanel from '@/components/ApiTokensPanel.vue'
import FormDialog from '@/components/FormDialog.vue'
import PageCard from '@/components/PageCard.vue'
import RowActions from '@/components/RowActions.vue'
import { useCrud } from '@/composables/useCrud'
import { useNotify } from '@/composables/useNotify'
import { formatDateTime } from '@/utils/datetime'
import { required } from '@/utils/rules'

const $q = useQuasar()
const notify = useNotify()
const groups = ref<UserGroup[]>([])
const eligibleGroups = computed(() => groups.value.filter((g) => g.source === 'internal' && !g.is_global_admin))

const crud = useCrud<ServiceAccount, ServiceAccountWrite>({
  api: serviceAccountsApi,
  noun: 'service account',
  describe: (account) => account.username,
  emptyForm: () => ({ username: '', description: '', is_active: true, groups: [] }),
  toForm: (account) => ({ ...account, groups: [...account.groups] }),
})

const columns: QTableColumn<ServiceAccount>[] = [
  { name: 'username', label: 'Name', field: 'username', align: 'left', sortable: true },
  { name: 'description', label: 'Description', field: 'description', align: 'left' },
  { name: 'status', label: 'Status', field: 'is_active', align: 'left' },
  { name: 'groups', label: 'User groups', field: (a) => a.group_names.join(' '), align: 'left' },
  { name: 'live_tokens', label: 'Live tokens', field: 'live_tokens', align: 'center', sortable: true },
  { name: 'actions', label: 'Actions', field: 'id', align: 'right' },
]

const allTokens = ref<ApiToken[]>([])
const loadingTokens = ref(false)
const tokenColumns: QTableColumn<ApiToken>[] = [
  { name: 'username', label: 'Owner', field: 'username', align: 'left', sortable: true },
  { name: 'name', label: 'Name', field: 'name', align: 'left', sortable: true },
  { name: 'prefix', label: 'Prefix', field: 'prefix', align: 'left' },
  { name: 'scopes', label: 'Scopes', field: (t) => t.scopes.join(', '), align: 'left' },
  { name: 'expires_at', label: 'Expires', field: 'expires_at', format: (v: string) => formatDateTime(v), align: 'left' },
  {
    name: 'last_used_at',
    label: 'Last used',
    field: 'last_used_at',
    format: (v: string | null) => (v ? formatDateTime(v) : 'Never'),
    align: 'left',
  },
  { name: 'actions', label: '', field: 'id', align: 'right' },
]

async function loadTokens(): Promise<void> {
  loadingTokens.value = true
  try {
    allTokens.value = await adminTokensApi.list()
  } catch (error) {
    notify.error(error, 'Failed to load tokens')
  } finally {
    loadingTokens.value = false
  }
}

function confirmRevoke(token: ApiToken): void {
  $q.dialog({
    title: 'Revoke token',
    message: `Revoke ${token.username}'s token "${token.name}" (${token.prefix})?`,
    cancel: true,
    persistent: true,
    ok: { label: 'Revoke', color: 'negative' },
  }).onOk(async () => {
    try {
      await adminTokensApi.revoke(token.id)
      notify.success('Token revoked')
      await Promise.all([loadTokens(), crud.load()])
    } catch (error) {
      notify.error(error, 'Failed to revoke the token')
    }
  })
}

const tokensOpen = ref(false)
const tokensFor = ref<ServiceAccount | null>(null)

function openTokens(account: ServiceAccount): void {
  tokensFor.value = account
  tokensOpen.value = true
}

watch(tokensOpen, (open) => {
  if (!open) void Promise.all([loadTokens(), crud.load()])
})

onMounted(async () => {
  void loadTokens()
  try {
    groups.value = await userGroupsApi.list()
  } catch (error) {
    notify.error(error, 'Failed to load user groups')
  }
})
</script>
