<!-- SPDX-License-Identifier: GPL-3.0-or-later -->
<template>
  <PageCard title="Backup Schedules" caption="Recurring backup times, in the application's display timezone">
    <template #actions>
      <q-btn color="primary" icon="add" label="Add Schedule" @click="crud.openCreate" />
    </template>

    <q-table flat :rows="crud.rows.value" :columns="columns" row-key="id" :loading="crud.loading.value" class="admin-table">
      <template #body-cell-enabled="props">
        <q-td :props="props">
          <q-badge :color="props.row.enabled ? 'positive' : 'grey'">{{ props.row.enabled ? 'Enabled' : 'Disabled' }}</q-badge>
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
      :title="crud.isEditing.value ? 'Edit Backup Schedule' : 'Add Backup Schedule'"
      :saving="crud.saving.value"
      @submit="crud.save"
    >
      <q-input v-model.trim="crud.form.value.name" label="Name" outlined autofocus :rules="[required]" />
      <q-input v-model="crud.form.value.description" label="Description" type="textarea" autogrow outlined />
      <q-select
        v-model="crud.form.value.schedule_type"
        :options="TYPE_OPTIONS"
        emit-value
        map-options
        label="Repeats"
        outlined
      />
      <q-input
        v-if="crud.form.value.schedule_type === 'custom_cron'"
        v-model.trim="crud.form.value.cron_expression"
        label="Cron expression"
        hint="minute hour day-of-month month day-of-week, e.g. 30 2 * * 1-5"
        outlined
        :rules="[required, cronFields]"
      />
      <template v-else>
        <div class="row q-col-gutter-md">
          <div class="col-6">
            <q-input
              v-model.number="crud.form.value.hour"
              type="number"
              label="Hour (0-23)"
              outlined
              :rules="[integerBetween(0, 23)]"
            />
          </div>
          <div class="col-6">
            <q-input
              v-model.number="crud.form.value.minute"
              type="number"
              label="Minute (0-59)"
              outlined
              :rules="[integerBetween(0, 59)]"
            />
          </div>
        </div>
        <q-select
          v-if="crud.form.value.schedule_type === 'weekly'"
          v-model="crud.form.value.day_of_week"
          :options="DAYS"
          emit-value
          map-options
          label="Day of week"
          outlined
        />
        <q-input
          v-if="crud.form.value.schedule_type === 'monthly'"
          v-model.number="crud.form.value.day_of_month"
          type="number"
          label="Day of month (1-31)"
          outlined
          :rules="[integerBetween(1, 31)]"
        />
      </template>
      <q-toggle v-model="crud.form.value.enabled" label="Enabled" />
    </FormDialog>
  </PageCard>
</template>

<script setup lang="ts">
import type { QTableColumn } from 'quasar'

import { backupSchedulesApi } from '@/api/endpoints'
import type { BackupSchedule, ScheduleType } from '@/api/types'
import FormDialog from '@/components/FormDialog.vue'
import PageCard from '@/components/PageCard.vue'
import RowActions from '@/components/RowActions.vue'
import { useCrud } from '@/composables/useCrud'
import { formatDateTime } from '@/utils/datetime'
import { integerBetween, required } from '@/utils/rules'

type Form = Omit<BackupSchedule, 'id' | 'created_at' | 'updated_at' | 'last_run_at' | 'next_run'>

const TYPE_OPTIONS: { label: string; value: ScheduleType }[] = [
  { label: 'Daily', value: 'daily' },
  { label: 'Weekly', value: 'weekly' },
  { label: 'Monthly', value: 'monthly' },
  { label: 'Custom (cron)', value: 'custom_cron' },
]
const DAY_NAMES = ['Sunday', 'Monday', 'Tuesday', 'Wednesday', 'Thursday', 'Friday', 'Saturday']
const DAYS = DAY_NAMES.map((label, value) => ({ label, value: String(value) }))

const cronFields = (value: string) => value.trim().split(/\s+/).length === 5 || 'A cron expression has 5 fields'

const crud = useCrud<BackupSchedule, Form>({
  api: backupSchedulesApi,
  noun: 'backup schedule',
  emptyForm: () => ({
    name: '',
    description: '',
    schedule_type: 'daily',
    hour: 0,
    minute: 0,
    day_of_week: '0',
    day_of_month: 1,
    cron_expression: '',
    enabled: true,
  }),
  toForm: ({ id: _id, created_at: _c, updated_at: _u, last_run_at: _l, next_run: _n, ...form }) => form,
})

const pad = (n: number) => String(n).padStart(2, '0')

function describe(schedule: BackupSchedule): string {
  const time = `${pad(schedule.hour)}:${pad(schedule.minute)}`
  switch (schedule.schedule_type) {
    case 'daily':
      return `Daily at ${time}`
    case 'weekly':
      return `Weekly on ${DAY_NAMES[Number(schedule.day_of_week)] ?? '?'} at ${time}`
    case 'monthly':
      return `Monthly on day ${schedule.day_of_month} at ${time}`
    default:
      return `Cron: ${schedule.cron_expression}`
  }
}

const columns: QTableColumn<BackupSchedule>[] = [
  { name: 'name', label: 'Name', field: 'name', align: 'left', sortable: true },
  { name: 'schedule', label: 'Schedule', field: (row) => describe(row), align: 'left' },
  { name: 'last_run_at', label: 'Last run', field: 'last_run_at', format: formatDateTime, align: 'left' },
  { name: 'next_run', label: 'Next run', field: 'next_run', format: formatDateTime, align: 'left' },
  { name: 'enabled', label: 'Status', field: 'enabled', align: 'center', sortable: true },
  { name: 'actions', label: 'Actions', field: 'id', align: 'right' },
]
</script>
