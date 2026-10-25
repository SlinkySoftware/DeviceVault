<!-- SPDX-License-Identifier: GPL-3.0-or-later -->
<template>
  <PageCard
    title="Retention Policies"
    caption="How long backups are kept. Any limit that is set applies; the newest backups and pinned ones are always kept."
  >
    <template #actions>
      <q-btn color="primary" icon="add" label="Add Policy" @click="crud.openCreate" />
    </template>

    <q-table flat :rows="crud.rows.value" :columns="columns" row-key="id" :loading="crud.loading.value" class="admin-table">
      <template #body-cell-mode="props">
        <q-td :props="props">
          <q-badge :color="props.row.dry_run ? 'grey' : 'warning'">{{ props.row.dry_run ? 'Dry run' : 'Enforced' }}</q-badge>
        </q-td>
      </template>
      <template #body-cell-last_run="props">
        <q-td :props="props">
          <TimeCell :value="props.row.last_run_at" />
          <div v-if="props.row.last_run_at" class="text-caption">{{ lastResult(props.row) }}</div>
        </q-td>
      </template>
      <template #body-cell-actions="props">
        <q-td :props="props">
          <RowActions @edit="crud.openEdit(props.row)" @delete="crud.confirmRemove(props.row)">
            <q-btn dense flat color="primary" icon="preview" label="Preview" @click="openPreview(props.row)" />
          </RowActions>
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
      <q-input
        v-model.number="crud.form.value.min_backups"
        type="number"
        label="Always keep the newest N backups"
        hint="Kept whatever the limits say (at least 1)"
        outlined
        :rules="[atLeastOne]"
      />
      <q-toggle v-model="crud.form.value.dry_run" label="Dry run: report what would be deleted, delete nothing" />
      <q-banner v-if="!crud.form.value.dry_run" dense rounded class="bg-warning text-dark">
        Expired backups will be deleted from their storage targets. Use Preview to check first; deleted backups
        cannot be recovered. Backups on git targets are always kept.
      </q-banner>
    </FormDialog>

    <q-dialog v-model="preview.open">
      <q-card style="width: 640px; max-width: 95vw">
        <q-card-section class="row items-center q-pb-none">
          <div class="text-h6">{{ preview.policy?.name }}: expired now</div>
          <q-space />
          <q-btn v-close-popup icon="close" flat round dense aria-label="Close" />
        </q-card-section>
        <q-card-section>
          <q-inner-loading :showing="preview.loading" />
          <template v-if="preview.result">
            <p>
              {{ preview.result.expired }} backup{{ preview.result.expired === 1 ? '' : 's' }}
              ({{ formatBytes(preview.result.expired_bytes) || '0 B' }})
              {{ preview.policy?.dry_run ? 'would be deleted' : 'will be deleted at the next retention pass' }}.
              <span v-if="preview.result.kept_undeletable">
                {{ preview.result.kept_undeletable }} more expired but stay, as their storage target keeps everything.
              </span>
            </p>
            <q-table
              v-if="preview.result.devices.length"
              flat
              dense
              :rows="preview.result.devices"
              :columns="previewColumns"
              row-key="device"
              :rows-per-page-options="[10, 50, 0]"
            />
          </template>
        </q-card-section>
      </q-card>
    </q-dialog>
  </PageCard>
</template>

<script setup lang="ts">
import type { QTableColumn } from 'quasar'
import { reactive } from 'vue'

import { retentionPoliciesApi } from '@/api/endpoints'
import type { RetentionPolicy, RetentionPolicyWrite, RetentionPreview } from '@/api/types'
import FormDialog from '@/components/FormDialog.vue'
import PageCard from '@/components/PageCard.vue'
import RowActions from '@/components/RowActions.vue'
import TimeCell from '@/components/TimeCell.vue'
import { useCrud } from '@/composables/useCrud'
import { useNotify } from '@/composables/useNotify'
import { formatDateTime } from '@/utils/datetime'
import { formatBytes } from '@/utils/format'
import { optionalNonNegativeInteger, required } from '@/utils/rules'

type Form = RetentionPolicyWrite
type Row = RetentionPreview['devices'][number]

const notify = useNotify()

// Cleared number inputs yield '' or null; the API wants null.
const toNullable = (value: number | string | null) => (value === '' || value === null ? null : Number(value))

const atLeastOne = (value: unknown): true | string =>
  (Number.isInteger(Number(value)) && Number(value) >= 1) || 'Must be a whole number of 1 or more'

const crud = useCrud<RetentionPolicy, Form>({
  api: {
    ...retentionPoliciesApi,
    create: (form) => retentionPoliciesApi.create(normalise(form)),
    update: (id, form) => retentionPoliciesApi.update(id, normalise(form)),
  },
  noun: 'retention policy',
  emptyForm: () => ({
    name: '',
    max_backups: null,
    max_days: null,
    max_size_bytes: null,
    min_backups: 1,
    dry_run: true,
  }),
})

function normalise(form: Form): Form {
  return {
    name: form.name,
    max_backups: toNullable(form.max_backups),
    max_days: toNullable(form.max_days),
    max_size_bytes: toNullable(form.max_size_bytes),
    min_backups: Number(form.min_backups),
    dry_run: form.dry_run,
  }
}

function lastResult(policy: RetentionPolicy): string {
  const { expired = 0, requested = 0, kept_undeletable: kept = 0 } = policy.last_result
  const parts = [policy.dry_run ? `${expired} would go` : `${requested} deleted, ${expired} expired`]
  if (kept) parts.push(`${kept} kept (target keeps everything)`)
  return parts.join(', ')
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
  { name: 'min_backups', label: 'Always Keep', field: 'min_backups', align: 'left' },
  { name: 'mode', label: 'Mode', field: 'dry_run', align: 'left' },
  { name: 'last_run', label: 'Last Run', field: 'last_run_at', align: 'left' },
  { name: 'actions', label: 'Actions', field: 'id', align: 'right' },
]

const previewColumns: QTableColumn<Row>[] = [
  { name: 'device', label: 'Device', field: 'device_name', align: 'left', sortable: true },
  { name: 'backups', label: 'Backups', field: 'backups', align: 'right', sortable: true },
  { name: 'bytes', label: 'Size', field: 'bytes', format: (value: number) => formatBytes(value) || '0 B', align: 'right' },
  { name: 'oldest', label: 'Oldest', field: 'oldest', format: formatDateTime, align: 'left' },
  { name: 'newest', label: 'Newest', field: 'newest', format: formatDateTime, align: 'left' },
]

const preview = reactive<{ open: boolean; loading: boolean; policy: RetentionPolicy | null; result: RetentionPreview | null }>({
  open: false,
  loading: false,
  policy: null,
  result: null,
})

async function openPreview(policy: RetentionPolicy): Promise<void> {
  Object.assign(preview, { open: true, loading: true, policy, result: null })
  try {
    preview.result = await retentionPoliciesApi.preview(policy.id)
  } catch (error) {
    preview.open = false
    notify.error(error, 'Failed to preview the policy')
  } finally {
    preview.loading = false
  }
}
</script>
