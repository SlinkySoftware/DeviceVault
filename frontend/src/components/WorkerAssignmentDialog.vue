<!-- SPDX-License-Identifier: GPL-3.0-or-later -->
<!-- Approve a worker, or change an approved worker's assignment. -->
<template>
  <FormDialog
    v-model="open"
    :title="approving ? `Approve ${worker?.name ?? 'worker'}` : `Assignment · ${worker?.name ?? ''}`"
    :submit-label="approving ? 'Approve' : 'Save'"
    :saving="saving"
    width="600px"
    @submit="submit"
  >
    <template v-if="worker">
      <q-banner v-if="approving" dense rounded class="bg-blue-1 text-black">
        <template #avatar><q-icon name="fingerprint" color="primary" /></template>
        Approve only if this fingerprint matches the one the worker printed in its log
        (<code>worker_identity</code>):
        <div class="fingerprint q-mt-xs">{{ worker.fingerprint }}</div>
      </q-banner>

      <q-select
        v-model="form.role"
        :options="roleOptions"
        emit-value
        map-options
        outlined
        label="Role"
        :rules="[(v: string) => !!v || 'Choose a role']"
      />

      <q-select
        v-if="form.role === 'collector'"
        v-model="form.collection_groups"
        :options="groups"
        option-value="id"
        option-label="name"
        emit-value
        map-options
        multiple
        use-chips
        outlined
        label="Collection groups"
        hint="The collector backs up devices in these groups"
      >
        <template #option="scope">
          <q-item v-bind="scope.itemProps">
            <q-item-section>
              <q-item-label>{{ scope.opt.name }}</q-item-label>
              <q-item-label caption>collector.group.{{ scope.opt.rabbitmq_queue_id }}</q-item-label>
            </q-item-section>
          </q-item>
        </template>
      </q-select>

      <q-select
        v-if="form.role === 'storage'"
        v-model="form.storage_backends"
        :options="backendOptions"
        emit-value
        map-options
        multiple
        use-chips
        outlined
        label="Storage backends"
        :rules="[(v: string[]) => v.length > 0 || 'Choose at least one backend']"
      />

      <div class="text-caption text-grey">
        Offers: {{ driverNames || 'no collector drivers' }} ·
        storage: {{ (worker.capabilities.storage_backends ?? []).join(', ') || 'none' }}
      </div>
    </template>
  </FormDialog>
</template>

<script setup lang="ts">
import { computed, reactive, ref, watch } from 'vue'

import { collectionGroupsApi, workersApi } from '@/api/endpoints'
import type { CollectionGroup, Worker, WorkerAssignment } from '@/api/types'
import FormDialog from '@/components/FormDialog.vue'
import { useNotify } from '@/composables/useNotify'

const props = defineProps<{ worker: Worker | null }>()
const open = defineModel<boolean>({ required: true })
const emit = defineEmits<{ saved: [worker: Worker] }>()

const BACKEND_LABELS: Record<string, string> = { fs: 'Filesystem', git: 'Git repository' }

const notify = useNotify()
const groups = ref<CollectionGroup[]>([])
const saving = ref(false)
const form = reactive<{ role: WorkerAssignment['role'] | ''; collection_groups: number[]; storage_backends: string[] }>({
  role: '',
  collection_groups: [],
  storage_backends: [],
})

const approving = computed(() => props.worker?.status !== 'approved')
const driverNames = computed(() =>
  (props.worker?.capabilities.collector_drivers ?? []).map((d) => d.name).join(', '),
)
const roleOptions = computed(() => [
  { label: 'Collector', value: 'collector', disable: !props.worker?.capabilities.collector_drivers?.length },
  { label: 'Storage', value: 'storage', disable: !props.worker?.capabilities.storage_backends?.length },
])
const backendOptions = computed(() =>
  (props.worker?.capabilities.storage_backends ?? []).map((b) => ({ label: BACKEND_LABELS[b] ?? b, value: b })),
)

watch(open, async (isOpen) => {
  if (!isOpen || !props.worker) return
  const worker = props.worker
  // No default role: every worker image can do both, so the admin must choose.
  Object.assign(form, {
    role: worker.role,
    collection_groups: [...worker.collection_groups],
    storage_backends: worker.storage_backends.length ? [...worker.storage_backends] : [],
  })
  try {
    groups.value = (await collectionGroupsApi.list()).sort((a, b) => a.name.localeCompare(b.name))
  } catch (error) {
    notify.error(error, 'Failed to load collection groups')
  }
})

async function submit(): Promise<void> {
  if (!props.worker || !form.role) return
  const body: WorkerAssignment = {
    role: form.role,
    collection_groups: form.role === 'collector' ? form.collection_groups : [],
    storage_backends: form.role === 'storage' ? form.storage_backends : [],
  }
  saving.value = true
  try {
    const saved = approving.value
      ? await workersApi.approve(props.worker.id, body)
      : await workersApi.update(props.worker.id, body)
    notify.success(approving.value ? `${saved.name} approved` : `${saved.name} reassigned`)
    open.value = false
    emit('saved', saved)
  } catch (error) {
    notify.error(error, 'Failed to save the worker assignment')
  } finally {
    saving.value = false
  }
}
</script>

<style scoped>
.fingerprint {
  font-family: ui-monospace, SFMono-Regular, Menlo, Consolas, monospace;
  font-weight: 600;
  word-break: break-all;
}
</style>
