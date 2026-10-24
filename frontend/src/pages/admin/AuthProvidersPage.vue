<!-- SPDX-License-Identifier: GPL-3.0-or-later -->
<template>
  <PageCard
    title="Auth Providers"
    caption="Directories and identity providers users sign in with; their groups map onto user groups at each sign-in"
  >
    <template #actions>
      <q-btn color="primary" icon="add" label="Add Provider" :disable="!kinds.length" @click="crud.openCreate" />
    </template>

    <q-table
      flat
      :rows="crud.rows.value"
      :columns="columns"
      row-key="id"
      :loading="crud.loading.value"
      no-data-label="No providers: only local accounts can sign in"
      class="admin-table"
    >
      <template #body-cell-name="props">
        <q-td :props="props">
          {{ props.row.name }}
          <q-badge v-if="!props.row.enabled" color="grey" class="q-ml-xs">Disabled</q-badge>
          <div class="text-caption text-muted">{{ props.row.slug }}</div>
        </q-td>
      </template>
      <template #body-cell-rules="props">
        <q-td :props="props">
          <div class="row q-gutter-xs">
            <q-chip v-for="rule in props.row.mapping_rules" :key="`${rule.external_group}-${rule.user_group}`" dense outline>
              {{ rule.external_group }} → {{ rule.user_group_name }}
            </q-chip>
            <span v-if="!props.row.mapping_rules.length" class="text-muted">No rules</span>
          </div>
        </q-td>
      </template>
      <template #body-cell-actions="props">
        <q-td :props="props">
          <RowActions
            @edit="crud.openEdit(props.row)"
            @delete="crud.confirmRemove(props.row, 'Its users can no longer sign in, and the memberships it added are removed.')"
          >
            <q-btn dense color="primary" icon="network_check" label="Test" @click="openTest(props.row)" />
          </RowActions>
        </q-td>
      </template>
    </q-table>

    <FormDialog
      v-model="crud.dialogOpen.value"
      :title="crud.isEditing.value ? `Edit ${editing?.name ?? 'provider'}` : 'Add Provider'"
      :saving="crud.saving.value"
      width="760px"
      @submit="crud.save"
    >
      <div class="row q-col-gutter-md">
        <q-input v-model.trim="crud.form.value.name" class="col-12 col-sm-6" label="Name" outlined :rules="[required]" />
        <q-input
          v-model.trim="crud.form.value.slug"
          class="col-12 col-sm-6"
          label="Slug"
          outlined
          :readonly="crud.isEditing.value"
          :rules="[required, slug]"
          hint="Fixed once created"
        />
        <q-select
          v-model="crud.form.value.kind"
          class="col-12 col-sm-6"
          :options="kinds"
          option-value="key"
          option-label="name"
          emit-value
          map-options
          outlined
          label="Kind"
          :readonly="crud.isEditing.value"
          :rules="[required]"
          @update:model-value="crud.form.value.config = {}"
        />
        <q-input
          v-model.number="crud.form.value.order"
          class="col-12 col-sm-6"
          type="number"
          min="0"
          label="Order"
          outlined
          hint="Password providers are tried in this order, after local accounts"
        />
      </div>
      <q-banner v-if="editing?.redirect_uri" dense rounded class="bg-info text-white">
        Register this redirect URI at the identity provider: <code>{{ editing.redirect_uri }}</code>
      </q-banner>
      <div class="row q-gutter-md">
        <q-toggle v-model="crud.form.value.enabled" label="Enabled" />
        <q-toggle v-model="crud.form.value.auto_create_users" label="Create users on first sign-in" />
        <q-toggle v-model="crud.form.value.auto_create_groups" label="Create external groups for unmapped groups" />
      </div>
      <q-input
        v-model.trim="crud.form.value.login_group"
        label="Required group (optional)"
        outlined
        hint="Only members of this provider group may sign in"
      />
      <DriverParamsForm
        v-model="crud.form.value.config"
        :schema="kind?.params_schema"
        :secrets-set="editing?.kind === crud.form.value.kind ? (editing?.secrets_set ?? []) : []"
        title="Settings"
      />

      <div>
        <div class="text-subtitle2 q-mb-sm">Group mapping rules</div>
        <div class="text-caption text-muted q-mb-sm">
          Members of a provider group join the user group. Memberships are set at each sign-in; manual ones are kept.
        </div>
        <div v-for="(rule, index) in crud.form.value.mapping_rules" :key="index" class="row q-col-gutter-sm items-center q-mb-xs">
          <q-input v-model.trim="rule.external_group" class="col" dense outlined label="Provider group" :rules="[required]" />
          <q-select
            v-model="rule.user_group"
            class="col"
            :options="userGroups"
            option-value="id"
            option-label="name"
            emit-value
            map-options
            dense
            outlined
            label="User group"
            :rules="[required]"
          />
          <div class="col-auto">
            <q-btn
              flat
              round
              dense
              icon="close"
              color="negative"
              aria-label="Remove rule"
              @click="crud.form.value.mapping_rules.splice(index, 1)"
            />
          </div>
        </div>
        <q-btn flat dense icon="add" label="Add rule" color="primary" @click="addRule" />
      </div>
    </FormDialog>

    <q-dialog v-model="test.open">
      <q-card style="width: 560px; max-width: 95vw">
        <q-card-section class="row items-center q-pb-none">
          <div class="text-h6">Test {{ test.provider?.name }}</div>
          <q-space />
          <q-btn v-close-popup icon="close" flat round dense aria-label="Close" />
        </q-card-section>
        <q-card-section class="q-gutter-md">
          <div class="row q-col-gutter-sm items-center">
            <q-input
              v-model.trim="test.username"
              class="col"
              dense
              outlined
              label="Look up a user (optional)"
              @keyup.enter="runTest"
            />
            <div class="col-auto">
              <q-btn color="primary" label="Run" :loading="test.running" @click="runTest" />
            </div>
          </div>
          <template v-if="test.result">
            <q-banner dense rounded :class="test.result.ok ? 'bg-positive text-white' : 'bg-negative text-white'">
              {{ test.result.ok ? `Connected to ${test.result.server ?? 'the provider'}` : test.result.error }}
            </q-banner>
            <div v-if="test.result.ok && test.username">
              <div v-if="test.result.user === null" class="text-orange">No such user</div>
              <q-list v-else-if="test.result.user" dense bordered separator>
                <q-item v-for="(value, key) in testedUser" :key="key">
                  <q-item-section side class="text-muted" style="min-width: 90px">{{ key }}</q-item-section>
                  <q-item-section>{{ value }}</q-item-section>
                </q-item>
              </q-list>
            </div>
          </template>
        </q-card-section>
      </q-card>
    </q-dialog>
  </PageCard>
</template>

<script setup lang="ts">
import type { QTableColumn } from 'quasar'
import { computed, onMounted, reactive, ref } from 'vue'

import { authProviderKindsApi, authProvidersApi, userGroupsApi } from '@/api/endpoints'
import type { AuthProvider, AuthProviderKind, AuthProviderWrite, ProviderTestResult, UserGroup } from '@/api/types'
import DriverParamsForm from '@/components/DriverParamsForm.vue'
import FormDialog from '@/components/FormDialog.vue'
import PageCard from '@/components/PageCard.vue'
import RowActions from '@/components/RowActions.vue'
import { useCrud } from '@/composables/useCrud'
import { useNotify } from '@/composables/useNotify'
import { required } from '@/utils/rules'

const notify = useNotify()
const kinds = ref<AuthProviderKind[]>([])
const userGroups = ref<UserGroup[]>([])
const editing = ref<AuthProvider | null>(null)

const slug = (value: string) => /^[a-z0-9-]+$/.test(value) || 'Lower-case letters, digits and "-" only'

const crud = useCrud<AuthProvider, AuthProviderWrite>({
  api: authProvidersApi,
  noun: 'provider',
  emptyForm: () => {
    editing.value = null
    return {
      slug: '',
      name: '',
      kind: kinds.value[0]?.key ?? '',
      enabled: true,
      order: 0,
      config: {},
      auto_create_users: true,
      auto_create_groups: false,
      login_group: '',
      mapping_rules: [],
    }
  },
  toForm: (row) => {
    editing.value = row
    return {
      slug: row.slug,
      name: row.name,
      kind: row.kind,
      enabled: row.enabled,
      order: row.order,
      config: { ...row.config },
      auto_create_users: row.auto_create_users,
      auto_create_groups: row.auto_create_groups,
      login_group: row.login_group,
      mapping_rules: row.mapping_rules.map(({ external_group, user_group }) => ({ external_group, user_group })),
    }
  },
})

const kind = computed(() => kinds.value.find((entry) => entry.key === crud.form.value.kind))

const columns: QTableColumn<AuthProvider>[] = [
  { name: 'order', label: 'Order', field: 'order', align: 'center', sortable: true },
  { name: 'name', label: 'Name', field: 'name', align: 'left', sortable: true },
  { name: 'kind', label: 'Kind', field: 'kind_name', align: 'left', sortable: true },
  { name: 'users', label: 'Users', field: 'user_count', align: 'center', sortable: true },
  { name: 'rules', label: 'Group mapping', field: (row) => row.mapping_rules.length, align: 'left' },
  { name: 'actions', label: 'Actions', field: 'id', align: 'right' },
]

function addRule(): void {
  crud.form.value.mapping_rules.push({ external_group: '', user_group: userGroups.value[0]?.id ?? 0 })
}

const test = reactive<{ open: boolean; provider: AuthProvider | null; username: string; running: boolean; result: ProviderTestResult | null }>({
  open: false,
  provider: null,
  username: '',
  running: false,
  result: null,
})

const testedUser = computed(() => {
  const user = test.result?.user
  if (!user) return {}
  return { ...user, groups: user.groups.join(', ') || '(none)' }
})

function openTest(provider: AuthProvider): void {
  Object.assign(test, { open: true, provider, result: null })
}

async function runTest(): Promise<void> {
  if (!test.provider) return
  test.running = true
  try {
    test.result = await authProvidersApi.test(test.provider.id, test.username)
  } catch (error) {
    notify.error(error, 'Failed to test the provider')
  } finally {
    test.running = false
  }
}

onMounted(async () => {
  try {
    ;[kinds.value, userGroups.value] = await Promise.all([authProviderKindsApi.list(), userGroupsApi.list()])
  } catch (error) {
    notify.error(error, 'Failed to load provider kinds and user groups')
  }
})
</script>
