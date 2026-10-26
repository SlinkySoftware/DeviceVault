<!-- SPDX-License-Identifier: GPL-3.0-or-later -->
<!-- One owner's API tokens: list, create (the token is shown once) and revoke. -->
<template>
  <div>
    <div class="row items-center q-mb-sm">
      <div class="text-caption text-grey col">
        Tokens act with {{ ownerLabel }} access, narrowed by their scopes. Send one as
        <code>Authorization: Bearer &lt;token&gt;</code>.
      </div>
      <q-btn color="primary" icon="key" label="Create Token" dense @click="openCreate" />
    </div>

    <q-table
      flat
      dense
      :rows="rows"
      :columns="columns"
      row-key="id"
      :loading="loading"
      hide-pagination
      :pagination="{ rowsPerPage: 0 }"
      no-data-label="No tokens"
    >
      <template #body-cell-scopes="props">
        <q-td :props="props">
          <q-chip v-for="scope in props.row.scopes" :key="scope" dense outline color="primary">
            {{ SCOPE_LABELS[scope as TokenScope] }}
          </q-chip>
        </q-td>
      </template>
      <template #body-cell-state="props">
        <q-td :props="props">
          <q-badge :color="props.row.state === 'live' ? 'positive' : 'grey'">
            {{ props.row.state === 'live' ? 'Live' : 'Expired' }}
          </q-badge>
        </q-td>
      </template>
      <template #body-cell-actions="props">
        <q-td :props="props">
          <q-btn dense color="negative" icon="block" label="Revoke" @click="confirmRevoke(props.row)" />
        </q-td>
      </template>
    </q-table>

    <FormDialog v-model="createOpen" title="Create API token" :saving="saving" submit-label="Create" @submit="create">
      <q-input v-model.trim="form.name" label="Name" outlined autofocus :rules="[required]" hint="What it is for, e.g. Zabbix" />
      <q-option-group v-model="form.scopes" :options="scopeOptions" type="checkbox" />
      <q-select
        v-model="form.expires_in_days"
        :options="expiryOptions"
        emit-value
        map-options
        outlined
        label="Expires after"
      />
      <q-input
        v-model="networks"
        label="Allowed networks (optional)"
        type="textarea"
        autogrow
        outlined
        hint="One address or CIDR per line; empty allows any address"
      />
    </FormDialog>

    <q-dialog v-model="shownOpen" persistent>
      <q-card style="width: 640px; max-width: 95vw">
        <q-card-section>
          <div class="text-h6">Token created</div>
          <div class="text-caption">Copy it now. It is not stored and will not be shown again.</div>
        </q-card-section>
        <q-card-section>
          <q-input :model-value="shownToken" readonly outlined dense input-class="text-mono">
            <template #append>
              <q-btn flat dense icon="content_copy" aria-label="Copy token" @click="copy" />
            </template>
          </q-input>
        </q-card-section>
        <q-card-actions align="right">
          <q-btn v-close-popup color="primary" label="Done" @click="shownToken = ''" />
        </q-card-actions>
      </q-card>
    </q-dialog>
  </div>
</template>

<script setup lang="ts">
import { copyToClipboard, useQuasar, type QTableColumn } from 'quasar'
import { computed, onMounted, reactive, ref } from 'vue'

import type { TokenApi } from '@/api/endpoints'
import type { ApiToken, ApiTokenWrite, TokenScope } from '@/api/types'
import FormDialog from '@/components/FormDialog.vue'
import { useNotify } from '@/composables/useNotify'
import { formatDateTime } from '@/utils/datetime'
import { required } from '@/utils/rules'
import { parseNetworks } from '@/utils/tokens'

const props = withDefaults(defineProps<{ api: TokenApi; ownerLabel?: string; allowPlatform?: boolean }>(), {
  ownerLabel: 'your',
  allowPlatform: false,
})

const $q = useQuasar()
const notify = useNotify()

const SCOPE_LABELS: Record<TokenScope, string> = {
  api: 'Full API',
  monitoring: 'Monitoring',
  monitoring_platform: 'Platform health',
}

const scopeOptions = computed(() => [
  { label: 'Full API: everything this account can do (except tokens and sign-in)', value: 'api' },
  { label: 'Monitoring: read-only monitoring endpoints', value: 'monitoring' },
  ...(props.allowPlatform
    ? [{ label: 'Platform health: workers, scheduler, storage targets and receivers', value: 'monitoring_platform' }]
    : []),
])

const expiryOptions = [
  { label: '30 days', value: 30 },
  { label: '90 days', value: 90 },
  { label: '180 days', value: 180 },
  { label: '1 year', value: 365 },
]

const rows = ref<ApiToken[]>([])
const loading = ref(false)
const createOpen = ref(false)
const saving = ref(false)
const shownOpen = ref(false)
const shownToken = ref('')
const networks = ref('')
const form = reactive<ApiTokenWrite>({ name: '', scopes: [], allowed_networks: [], expires_in_days: 90 })

const columns: QTableColumn<ApiToken>[] = [
  { name: 'name', label: 'Name', field: 'name', align: 'left', sortable: true },
  { name: 'prefix', label: 'Prefix', field: 'prefix', align: 'left' },
  { name: 'scopes', label: 'Scopes', field: (t) => t.scopes.join(' '), align: 'left' },
  { name: 'state', label: 'State', field: 'state', align: 'left' },
  { name: 'expires_at', label: 'Expires', field: 'expires_at', format: (v: string) => formatDateTime(v), align: 'left' },
  {
    name: 'last_used_at',
    label: 'Last used',
    field: (t) => (t.last_used_at ? `${formatDateTime(t.last_used_at)} from ${t.last_used_address ?? '?'}` : 'Never'),
    align: 'left',
  },
  { name: 'actions', label: '', field: 'id', align: 'right' },
]

async function load(): Promise<void> {
  loading.value = true
  try {
    rows.value = await props.api.list()
  } catch (error) {
    notify.error(error, 'Failed to load tokens')
  } finally {
    loading.value = false
  }
}

function openCreate(): void {
  Object.assign(form, {
    name: '',
    scopes: [props.allowPlatform ? 'monitoring' : 'api'],
    allowed_networks: [],
    expires_in_days: 90,
  })
  networks.value = ''
  createOpen.value = true
}

async function create(): Promise<void> {
  if (!form.scopes.length) {
    notify.warning('Choose at least one scope')
    return
  }
  saving.value = true
  try {
    const created = await props.api.create({ ...form, allowed_networks: parseNetworks(networks.value) })
    createOpen.value = false
    shownToken.value = created.token
    shownOpen.value = true
    await load()
  } catch (error) {
    notify.error(error, 'Failed to create the token')
  } finally {
    saving.value = false
  }
}

async function copy(): Promise<void> {
  try {
    await copyToClipboard(shownToken.value)
    notify.success('Token copied')
  } catch {
    notify.warning('Copy failed; select the token and copy it by hand')
  }
}

function confirmRevoke(token: ApiToken): void {
  $q.dialog({
    title: 'Revoke token',
    message: `Revoke "${token.name}" (${token.prefix})? Anything using it stops working at once.`,
    cancel: true,
    persistent: true,
    ok: { label: 'Revoke', color: 'negative' },
  }).onOk(async () => {
    try {
      await props.api.revoke(token.id)
      notify.success('Token revoked')
      await load()
    } catch (error) {
      notify.error(error, 'Failed to revoke the token')
    }
  })
}

onMounted(load)
defineExpose({ load })
</script>

<style scoped>
.text-mono {
  font-family: monospace;
}
</style>
