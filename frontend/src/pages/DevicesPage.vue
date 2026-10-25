<!-- SPDX-License-Identifier: GPL-3.0-or-later -->
<template>
  <PageCard title="Devices" caption="Network devices and their backup status">
    <template #actions>
      <q-btn v-if="canAdd" color="primary" icon="add" label="Add Device" :to="{ name: 'device-new' }" />
    </template>

    <div class="row q-col-gutter-md q-mb-md">
      <div class="col-12 col-sm-6 col-md-2">
        <q-select
          v-model="filters.lifecycle"
          :options="LIFECYCLE_OPTIONS"
          emit-value
          map-options
          outlined
          dense
          label="Show"
        />
      </div>
      <div class="col-12 col-sm-6 col-md-3">
        <q-input v-model="filters.name" outlined dense clearable label="Name or IP" debounce="200">
          <template #prepend><q-icon name="search" /></template>
        </q-input>
      </div>
      <div class="col-12 col-sm-6 col-md-2">
        <q-select
          v-model="filters.type"
          :options="deviceTypes"
          option-value="id"
          option-label="name"
          emit-value
          map-options
          outlined
          dense
          clearable
          label="Device type"
        />
      </div>
      <div class="col-12 col-sm-6 col-md-3">
        <q-select
          v-model="filters.group"
          :options="deviceGroups"
          option-value="id"
          option-label="name"
          emit-value
          map-options
          outlined
          dense
          clearable
          label="Device group"
        />
      </div>
      <div class="col-12 col-sm-6 col-md-2">
        <q-select
          v-model="filters.status"
          :options="STATUS_OPTIONS"
          emit-value
          map-options
          outlined
          dense
          clearable
          label="Last backup"
        />
      </div>
    </div>

    <q-table
      flat
      :rows="filteredDevices"
      :columns="columns"
      row-key="id"
      :loading="loading"
      :pagination="{ rowsPerPage: 25, sortBy: 'name' }"
      class="admin-table"
    >
      <template #body-cell-type="props">
        <q-td :props="props">
          <q-icon :name="props.row.device_type?.icon || 'router'" size="sm" color="primary" class="q-mr-sm" />
          {{ props.row.device_type?.name }}
        </q-td>
      </template>
      <template #body-cell-group="props">
        <q-td :props="props">
          <q-badge color="info" outline>{{ props.row.device_group_name || 'Unassigned' }}</q-badge>
        </q-td>
      </template>
      <template #body-cell-last_backup_time="props">
        <q-td :props="props">
          <template v-if="props.row.last_backup_time">
            <q-badge :color="statusColor(props.row.last_backup_status)" class="q-mr-sm">
              {{ props.row.last_backup_status }}
            </q-badge>
            <span :title="formatDateTime(props.row.last_backup_time)">{{ formatDateTimeShort(props.row.last_backup_time) }}</span>
          </template>
          <span v-else class="text-grey">Never</span>
        </q-td>
      </template>
      <template #body-cell-name="props">
        <q-td :props="props">
          {{ props.row.name }}
          <template v-if="props.row.lifecycle !== 'active'">
            <q-badge color="grey-7" class="q-ml-xs">
              Inactive
              <q-tooltip>{{ inactiveSummary(props.row) }}</q-tooltip>
            </q-badge>
            <q-badge :color="props.row.lifecycle === 'deletable' ? 'negative' : 'grey'" outline class="q-ml-xs">
              {{ holdLabel(props.row) }}
            </q-badge>
          </template>
          <q-badge v-else-if="!props.row.enabled" color="grey" class="q-ml-xs">Disabled</q-badge>
        </q-td>
      </template>
      <template #body-cell-actions="props">
        <q-td :props="props" class="no-wrap">
          <q-btn
            dense
            round
            flat
            color="primary"
            icon="settings"
            :aria-label="can(props.row, 'admin') ? 'Configure' : 'View'"
            :to="{ name: 'device-edit', params: { id: props.row.id } }"
          >
            <q-tooltip>{{ can(props.row, 'admin') ? 'Configure' : 'View' }}</q-tooltip>
          </q-btn>
          <q-btn
            v-if="can(props.row, 'view')"
            dense
            round
            flat
            color="primary"
            icon="history"
            aria-label="Backups"
            :to="{ name: 'device-backups', params: { id: props.row.id } }"
          >
            <q-tooltip>Backups</q-tooltip>
          </q-btn>
          <q-btn
            v-if="can(props.row, 'backup_now') && props.row.lifecycle === 'active'"
            dense
            round
            flat
            color="positive"
            icon="play_arrow"
            aria-label="Backup now"
            :loading="dispatching.has(props.row.id)"
            @click="backupNow(props.row)"
          >
            <q-tooltip>Backup now</q-tooltip>
          </q-btn>
          <q-btn
            v-if="can(props.row, 'admin')"
            dense
            round
            flat
            :color="STEPS[nextStep(props.row)].color"
            :icon="STEPS[nextStep(props.row)].icon"
            :aria-label="STEPS[nextStep(props.row)].label"
            :loading="dispatching.has(props.row.id)"
            @click="takeStep(props.row)"
          >
            <q-tooltip>{{ STEPS[nextStep(props.row)].label }}</q-tooltip>
          </q-btn>
          <q-btn
            v-if="auth.isGlobalAdmin && props.row.lifecycle === 'inactive' && !props.row.purge_requested_at"
            dense
            round
            flat
            color="negative"
            icon="delete_sweep"
            aria-label="Purge backups now"
            @click="confirmPurge(props.row)"
          >
            <q-tooltip>Purge backups now</q-tooltip>
          </q-btn>
        </q-td>
      </template>
    </q-table>

    <FormDialog
      v-model="retiring.open"
      :title="`Mark ${retiring.device?.name ?? ''} inactive`"
      submit-label="Mark inactive"
      :saving="retiring.saving"
      @submit="deactivate"
    >
      <p class="q-mb-none">
        The device is no longer backed up and no longer accepted by the receivers. Its backups stay readable.
        {{ retiring.hold }}
      </p>
      <q-input
        v-model="retiring.reason"
        outlined
        label="Reason (optional)"
        hint="For example: replaced by core-sw-02"
        maxlength="200"
        counter
      />
    </FormDialog>
  </PageCard>
</template>

<script setup lang="ts">
import type { QTableColumn } from 'quasar'
import { useQuasar } from 'quasar'
import { computed, onMounted, reactive, ref } from 'vue'

import { backupJobsApi, deviceGroupsApi, devicesApi, deviceTypesApi, retentionPoliciesApi } from '@/api/endpoints'
import type { Device, DeviceGroup, DeviceType, GrantFlag, Id } from '@/api/types'
import FormDialog from '@/components/FormDialog.vue'
import PageCard from '@/components/PageCard.vue'
import { useNotify } from '@/composables/useNotify'
import { useAuthStore } from '@/stores/auth'
import { formatDateTime, formatDateTimeShort } from '@/utils/datetime'
import { formatBytes, statusColor } from '@/utils/format'
import { holdLabel, inactiveSummary, nextStep } from '@/utils/lifecycle'

const STATUS_OPTIONS = [
  { label: 'Success', value: 'success' },
  { label: 'Failure', value: 'failure' },
  { label: 'Never backed up', value: 'never' },
]

const LIFECYCLE_OPTIONS = [
  { label: 'Active devices', value: 'active' },
  { label: 'Inactive devices', value: 'inactive' },
  { label: 'All devices', value: 'all' },
]

const STEPS = {
  deactivate: { label: 'Mark inactive', icon: 'archive', color: 'grey-8' },
  reactivate: { label: 'Reactivate', icon: 'unarchive', color: 'primary' },
  delete: { label: 'Delete', icon: 'delete', color: 'negative' },
} as const

const $q = useQuasar()
const auth = useAuthStore()
const notify = useNotify()

const devices = ref<Device[]>([])
const deviceTypes = ref<DeviceType[]>([])
const deviceGroups = ref<DeviceGroup[]>([])
const loading = ref(false)
const dispatching = reactive(new Set<Id>())
const filters = reactive<{
  lifecycle: string
  name: string | null
  type: Id | null
  group: Id | null
  status: string | null
}>({
  lifecycle: 'active',
  name: '',
  type: null,
  group: null,
  status: null,
})

const columns: QTableColumn<Device>[] = [
  { name: 'name', label: 'Name', field: 'name', align: 'left', sortable: true },
  { name: 'group', label: 'Group', field: (row) => row.device_group_name ?? '', align: 'left', sortable: true },
  { name: 'ip_address', label: 'IP', field: 'ip_address', align: 'left', sortable: true },
  { name: 'type', label: 'Type', field: (row) => row.device_type?.name ?? '', align: 'left', sortable: true },
  { name: 'backup_method', label: 'Method', field: 'backup_method_display', align: 'left', sortable: true },
  {
    name: 'last_backup_time',
    label: 'Last Backup',
    field: 'last_backup_time',
    align: 'left',
    sortable: true,
  },
  { name: 'actions', label: 'Actions', field: 'id', align: 'right' },
]

const can = (device: Device, flag: GrantFlag) => device.user_permissions.includes(flag)
const canAdd = computed(() => auth.administersAny)

const filteredDevices = computed(() => {
  const needle = (filters.name ?? '').trim().toLowerCase()
  return devices.value.filter((device) => {
    if (filters.lifecycle === 'active' && device.lifecycle !== 'active') return false
    if (filters.lifecycle === 'inactive' && device.lifecycle === 'active') return false
    if (needle && !device.name.toLowerCase().includes(needle) && !device.ip_address.includes(needle)) return false
    if (filters.type !== null && device.device_type?.id !== filters.type) return false
    if (filters.group !== null && device.device_group !== filters.group) return false
    if (filters.status === 'never') return !device.last_backup_status
    if (filters.status && device.last_backup_status !== filters.status) return false
    return true
  })
})

async function backupNow(device: Device): Promise<void> {
  dispatching.add(device.id)
  try {
    const { created } = await devicesApi.backupNow(device.id)
    notify.success(created ? `Backup of ${device.name} queued` : `A backup of ${device.name} is already in progress`)
  } catch (error) {
    notify.error(error, `Failed to start backup of ${device.name}`)
  } finally {
    dispatching.delete(device.id)
  }
}

// --- Retiring devices (ARCHITECTURE.md 7.5) ---

const retiring = reactive<{ open: boolean; saving: boolean; device: Device | null; reason: string; hold: string }>({
  open: false,
  saving: false,
  device: null,
  reason: '',
  hold: '',
})

async function holdDescription(device: Device): Promise<string> {
  if (device.retention_policy === null) return 'It has no retention policy, so its backups are kept until someone acts.'
  try {
    const policy = await retentionPoliciesApi.get(device.retention_policy)
    if (policy.inactive_keep_days === null) {
      return `Its retention policy "${policy.name}" keeps the backups of inactive devices indefinitely.`
    }
    return (
      `Its retention policy "${policy.name}" keeps them for ${policy.inactive_keep_days} days, ` +
      'then deletes every backup that is not pinned. The device can then be deleted.'
    )
  } catch {
    return ''
  }
}

async function takeStep(device: Device): Promise<void> {
  const step = nextStep(device)
  if (step === 'deactivate') {
    Object.assign(retiring, { open: true, saving: false, device, reason: '', hold: '' })
    retiring.hold = await holdDescription(device)
  } else if (step === 'reactivate') {
    await run(device, () => devicesApi.reactivate(device.id), `${device.name} is active again`)
  } else {
    confirmDelete(device)
  }
}

async function deactivate(): Promise<void> {
  const device = retiring.device
  if (!device) return
  retiring.saving = true
  try {
    await devicesApi.deactivate(device.id, retiring.reason)
    retiring.open = false
    notify.success(`${device.name} marked inactive`)
    await loadDevices()
  } catch (error) {
    notify.error(error, `Failed to mark ${device.name} inactive`)
  } finally {
    retiring.saving = false
  }
}

async function run(device: Device, action: () => Promise<unknown>, done: string): Promise<void> {
  dispatching.add(device.id)
  try {
    await action()
    notify.success(done)
    await loadDevices()
  } catch (error) {
    notify.error(error, `Failed to change ${device.name}`)
  } finally {
    dispatching.delete(device.id)
  }
}

/** A prompt that enables OK only once the device name is typed. */
function confirmByName(device: Device, title: string, message: string, ok: string): Promise<boolean> {
  return new Promise((resolve) => {
    $q.dialog({
      title,
      message: `${message}\n\nType ${device.name} to confirm.`,
      style: 'white-space: pre-line',
      prompt: { model: '', type: 'text', isValid: (value: string) => value === device.name },
      cancel: true,
      persistent: true,
      ok: { label: ok, color: 'negative' },
    })
      .onOk(() => resolve(true))
      .onCancel(() => resolve(false))
  })
}

async function confirmDelete(device: Device): Promise<void> {
  const message =
    `${device.name} and its backup history are deleted. This cannot be undone.` +
    (device.lifecycle === 'deletable'
      ? ' Backups on storage targets that keep everything (git) stay in their history.'
      : '')
  if (await confirmByName(device, `Delete ${device.name}`, message, 'Delete')) {
    await run(device, () => devicesApi.remove(device.id), `${device.name} deleted`)
  }
}

async function confirmPurge(device: Device): Promise<void> {
  let pinned = ''
  if (device.pinned_backups) {
    try {
      const page = await backupJobsApi.list({ device: device.id, pinned: true, page_size: 20 })
      const labels = page.results.map((job) => `• ${formatDateTime(job.created_at)} ${job.label}`.trim())
      pinned = `\n\nThese pinned backups are unpinned and deleted too:\n${labels.join('\n')}`
    } catch {
      pinned = `\n\n${device.pinned_backups} pinned backup(s) are unpinned and deleted too.`
    }
  }
  const message =
    `All ${device.held_backups} backups of ${device.name} (${formatBytes(device.held_bytes)}) are deleted now, ` +
    `whatever its retention policy says. This cannot be undone.${pinned}`
  if (await confirmByName(device, `Purge the backups of ${device.name}`, message, 'Purge')) {
    await run(device, () => devicesApi.purge(device.id, device.name), `Deleting the backups of ${device.name}`)
  }
}

async function loadDevices(): Promise<void> {
  devices.value = await devicesApi.list()
}

onMounted(async () => {
  loading.value = true
  try {
    const byName = <T extends { name: string }>(a: T, b: T) => a.name.localeCompare(b.name)
    const [, types, groups] = await Promise.all([loadDevices(), deviceTypesApi.list(), deviceGroupsApi.list()])
    deviceTypes.value = types.sort(byName)
    deviceGroups.value = groups.sort(byName)
  } catch (error) {
    notify.error(error, 'Failed to load devices')
  } finally {
    loading.value = false
  }
})
</script>
