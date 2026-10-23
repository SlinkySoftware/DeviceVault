<!-- SPDX-License-Identifier: GPL-3.0-or-later -->
<template>
  <PageCard title="Devices" caption="Network devices and their backup status">
    <template #actions>
      <q-btn v-if="canAdd" color="primary" icon="add" label="Add Device" :to="{ name: 'device-new' }" />
    </template>

    <div class="row q-col-gutter-md q-mb-md">
      <div class="col-12 col-sm-6 col-md-3">
        <q-input v-model="filters.name" outlined dense clearable label="Name or IP" debounce="200">
          <template #prepend><q-icon name="search" /></template>
        </q-input>
      </div>
      <div class="col-12 col-sm-6 col-md-3">
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
      <div class="col-12 col-sm-6 col-md-3">
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
      <template #body-cell-status="props">
        <q-td :props="props">
          <q-badge v-if="props.row.last_backup_status" :color="statusColor(props.row.last_backup_status)">
            {{ props.row.last_backup_status }}
          </q-badge>
          <span v-else class="text-grey">Never</span>
        </q-td>
      </template>
      <template #body-cell-enabled="props">
        <q-td :props="props">
          <q-badge :color="props.row.enabled ? 'positive' : 'grey'">
            {{ props.row.enabled ? 'Enabled' : 'Disabled' }}
          </q-badge>
        </q-td>
      </template>
      <template #body-cell-actions="props">
        <q-td :props="props" class="q-gutter-xs">
          <q-btn
            v-if="can(props.row, 'view') || can(props.row, 'modify')"
            dense
            color="primary"
            icon="settings"
            :label="can(props.row, 'modify') ? 'Configure' : 'View'"
            :to="{ name: 'device-edit', params: { id: props.row.id } }"
          />
          <q-btn
            v-if="can(props.row, 'view_backups')"
            dense
            color="primary"
            icon="history"
            label="Backups"
            :to="{ name: 'device-backups', params: { id: props.row.id } }"
          />
          <q-btn
            v-if="can(props.row, 'backup_now')"
            dense
            color="primary"
            icon="play_arrow"
            label="Backup Now"
            :loading="dispatching.has(props.row.id)"
            @click="backupNow(props.row)"
          />
        </q-td>
      </template>
    </q-table>
  </PageCard>
</template>

<script setup lang="ts">
import type { QTableColumn } from 'quasar'
import { computed, onMounted, reactive, ref } from 'vue'

import { deviceGroupsApi, devicesApi, deviceTypesApi } from '@/api/endpoints'
import type { Device, DeviceGroup, DevicePermission, DeviceType, Id } from '@/api/types'
import PageCard from '@/components/PageCard.vue'
import { useNotify } from '@/composables/useNotify'
import { useAuthStore } from '@/stores/auth'
import { formatDateTime } from '@/utils/datetime'
import { statusColor } from '@/utils/format'

const STATUS_OPTIONS = [
  { label: 'Success', value: 'success' },
  { label: 'Failure', value: 'failure' },
  { label: 'Never backed up', value: 'never' },
]

const auth = useAuthStore()
const notify = useNotify()

const devices = ref<Device[]>([])
const deviceTypes = ref<DeviceType[]>([])
const deviceGroups = ref<DeviceGroup[]>([])
const loading = ref(false)
const dispatching = reactive(new Set<Id>())
const filters = reactive<{ name: string | null; type: Id | null; group: Id | null; status: string | null }>({
  name: '',
  type: null,
  group: null,
  status: null,
})

const columns: QTableColumn<Device>[] = [
  { name: 'name', label: 'Name', field: 'name', align: 'left', sortable: true },
  { name: 'group', label: 'Device Group', field: (row) => row.device_group_name ?? '', align: 'left', sortable: true },
  { name: 'ip_address', label: 'IP', field: 'ip_address', align: 'left', sortable: true },
  { name: 'type', label: 'Type', field: (row) => row.device_type?.name ?? '', align: 'left', sortable: true },
  { name: 'backup_method', label: 'Backup Method', field: 'backup_method_display', align: 'left', sortable: true },
  {
    name: 'last_backup_time',
    label: 'Last Backup',
    field: 'last_backup_time',
    format: (value: string | null) => (value ? formatDateTime(value) : 'Never'),
    align: 'left',
    sortable: true,
  },
  { name: 'status', label: 'Status', field: 'last_backup_status', align: 'center', sortable: true },
  { name: 'enabled', label: 'Enabled', field: 'enabled', align: 'center', sortable: true },
  { name: 'actions', label: 'Actions', field: 'id', align: 'right' },
]

const can = (device: Device, permission: DevicePermission) => device.user_permissions.includes(permission)
const canAdd = computed(() => auth.isAdmin || deviceGroups.value.some((g) => g.user_permissions.includes('modify')))

const filteredDevices = computed(() => {
  const needle = (filters.name ?? '').trim().toLowerCase()
  return devices.value.filter((device) => {
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
    const { queued_on } = await devicesApi.backupNow(device.id)
    notify.success(`Backup of ${device.name} queued on ${queued_on}`)
  } catch (error) {
    notify.error(error, `Failed to start backup of ${device.name}`)
  } finally {
    dispatching.delete(device.id)
  }
}

onMounted(async () => {
  loading.value = true
  try {
    const byName = <T extends { name: string }>(a: T, b: T) => a.name.localeCompare(b.name)
    const [deviceList, types, groups] = await Promise.all([
      devicesApi.list(),
      deviceTypesApi.list(),
      deviceGroupsApi.list(),
    ])
    devices.value = deviceList
    deviceTypes.value = types.sort(byName)
    deviceGroups.value = groups.sort(byName)
  } catch (error) {
    notify.error(error, 'Failed to load devices')
  } finally {
    loading.value = false
  }
})
</script>
