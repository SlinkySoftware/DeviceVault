<!-- SPDX-License-Identifier: GPL-3.0-or-later -->
<template>
  <PageCard title="Storage Targets" caption="Where backups are written, and which storage workers write them">
    <template #actions>
      <q-btn color="primary" icon="add" label="Add Target" :disable="!drivers.length" @click="crud.openCreate">
        <q-tooltip v-if="!drivers.length">Approve a storage worker first (Admin Settings > Workers)</q-tooltip>
      </q-btn>
    </template>

    <q-table flat :rows="crud.rows.value" :columns="columns" row-key="id" :loading="crud.loading.value" class="admin-table">
      <template #body-cell-workers="props">
        <q-td :props="props">
          <q-chip v-for="name in props.row.worker_names" :key="name" dense icon="dns">{{ name }}</q-chip>
          <span v-if="!props.row.worker_names?.length" class="text-negative">
            <q-icon name="warning" /> No worker: backups to this target cannot run
          </span>
        </q-td>
      </template>
      <template #body-cell-actions="props">
        <q-td :props="props">
          <RowActions
            :delete-disabled="(props.row.job_count ?? 0) > 0"
            delete-disabled-reason="This target holds backups"
            @edit="crud.openEdit(props.row)"
            @delete="crud.confirmRemove(props.row)"
          >
            <q-btn dense color="info" icon="network_check" label="Test" :loading="checking.has(props.row.id)" @click="check(props.row)" />
          </RowActions>
        </q-td>
      </template>
    </q-table>

    <FormDialog
      v-model="crud.dialogOpen.value"
      :title="crud.isEditing.value ? 'Edit Storage Target' : 'Add Storage Target'"
      :saving="crud.saving.value"
      width="640px"
      @submit="crud.save"
    >
      <q-input v-model.trim="crud.form.value.name" label="Name" outlined autofocus :rules="[required]" />
      <q-input v-model="crud.form.value.description" label="Description" type="textarea" autogrow outlined />
      <q-select
        v-model="crud.form.value.driver"
        :options="drivers"
        option-value="key"
        option-label="name"
        emit-value
        map-options
        outlined
        label="Storage driver"
        :hint="driver?.description"
        :disable="holdsBackups"
        :rules="[required]"
        @update:model-value="onDriverChange"
      />
      <q-banner v-if="holdsBackups" dense rounded class="bg-warning text-black">
        This target holds {{ editing?.job_count }} backups. Its driver cannot change, and changing where it writes
        (a path or bucket) makes earlier backups unreadable unless their data moves too.
      </q-banner>
      <DriverParamsForm
        v-model="crud.form.value.config"
        :schema="driver?.params_schema"
        :secrets-set="editing?.secrets_set ?? []"
        title="Settings"
      />
      <q-select
        v-model="crud.form.value.workers"
        :options="workerOptions"
        option-value="id"
        option-label="name"
        emit-value
        map-options
        multiple
        use-chips
        outlined
        label="Storage workers"
        :hint="
          driver?.shareable
            ? 'Any of these workers can store and read backups for this target'
            : 'This driver writes to one worker\'s own volume, so choose one worker'
        "
        :rules="[(v: string[]) => driver?.shareable || v.length <= 1 || 'Choose one worker for this driver']"
      >
        <template #no-option>
          <q-item><q-item-section class="text-grey">No approved storage worker offers this driver</q-item-section></q-item>
        </template>
      </q-select>
    </FormDialog>
  </PageCard>
</template>

<script setup lang="ts">
import type { QTableColumn } from 'quasar'
import { computed, onMounted, reactive, ref } from 'vue'

import { storageDriversApi, storageTargetsApi, workersApi } from '@/api/endpoints'
import type { StorageDriver, StorageTarget, StorageTargetWrite, Worker } from '@/api/types'
import DriverParamsForm from '@/components/DriverParamsForm.vue'
import FormDialog from '@/components/FormDialog.vue'
import PageCard from '@/components/PageCard.vue'
import RowActions from '@/components/RowActions.vue'
import { useCrud } from '@/composables/useCrud'
import { useNotify } from '@/composables/useNotify'
import { required } from '@/utils/rules'
import { keepKnown } from '@/utils/schema'

const notify = useNotify()
const drivers = ref<StorageDriver[]>([])
const workers = ref<Worker[]>([])
const editing = ref<StorageTarget | null>(null)

const crud = useCrud<StorageTarget, StorageTargetWrite>({
  api: storageTargetsApi,
  noun: 'storage target',
  emptyForm: () => {
    editing.value = null
    return { name: '', description: '', driver: drivers.value[0]?.key ?? '', config: {}, workers: [] }
  },
  toForm: (row) => {
    editing.value = row
    return {
      name: row.name,
      description: row.description,
      driver: row.driver,
      // Secrets come back empty; left empty, the server keeps them.
      config: Object.fromEntries(Object.entries(row.config ?? {}).filter(([, value]) => value !== null)),
      workers: [...(row.workers ?? [])],
    }
  },
})

const driver = computed(() => drivers.value.find((d) => d.key === crud.form.value.driver))
const holdsBackups = computed(() => (editing.value?.job_count ?? 0) > 0)

const offers = (worker: Worker, key: string) => (worker.capabilities.storage_drivers ?? []).some((d) => d.key === key)
const workerOptions = computed(() =>
  workers.value.filter((w) => w.status === 'approved' && w.role === 'storage' && offers(w, crud.form.value.driver)),
)

function onDriverChange(key: string): void {
  const next = drivers.value.find((d) => d.key === key)
  crud.form.value.config = keepKnown(crud.form.value.config, next?.params_schema)
  crud.form.value.workers = crud.form.value.workers.filter((id) => {
    const worker = workers.value.find((w) => w.id === id)
    return worker && offers(worker, key)
  })
}

const checking = reactive(new Set<string>())

async function check(target: StorageTarget): Promise<void> {
  checking.add(target.id)
  try {
    const result = await storageTargetsApi.check(target.id)
    if (result.ok) notify.success(`${target.name} works (${result.worker}: ${result.message})`)
    else notify.warning(`${target.name} failed its check: ${result.error ?? 'unknown error'}`)
  } catch (error) {
    notify.error(error, `Failed to check ${target.name}`)
  } finally {
    checking.delete(target.id)
  }
}

const columns: QTableColumn<StorageTarget>[] = [
  { name: 'name', label: 'Name', field: 'name', align: 'left', sortable: true },
  { name: 'driver', label: 'Driver', field: (row) => row.driver_name ?? row.driver, align: 'left', sortable: true },
  { name: 'workers', label: 'Workers', field: 'worker_names', align: 'left' },
  { name: 'devices', label: 'Devices', field: 'device_count', align: 'right', sortable: true },
  { name: 'backups', label: 'Backups', field: 'job_count', align: 'right', sortable: true },
  { name: 'actions', label: 'Actions', field: 'id', align: 'right' },
]

onMounted(async () => {
  try {
    ;[drivers.value, workers.value] = await Promise.all([storageDriversApi.list(), workersApi.list()])
  } catch (error) {
    notify.error(error, 'Failed to load storage drivers and workers')
  }
})
</script>
