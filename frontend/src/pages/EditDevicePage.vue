<!-- SPDX-License-Identifier: GPL-3.0-or-later -->
<template>
  <q-page padding>
    <div class="row items-center q-mb-md">
      <div class="text-h5 col">{{ title }}</div>
      <q-badge v-if="isEdit" :color="form.enabled ? 'positive' : 'negative'" class="text-body2 q-pa-sm">
        {{ form.enabled ? 'Backups enabled' : 'Backups disabled' }}
      </q-badge>
    </div>

    <q-card v-if="device" class="q-mb-md">
      <q-card-section class="row q-col-gutter-md">
        <div class="col-12 col-sm-6">
          <div class="text-subtitle2">Last backup status</div>
          <q-badge :color="statusColor(device.last_backup_status)" class="text-h6 q-pa-sm">
            {{ device.last_backup_status || 'Never backed up' }}
          </q-badge>
        </div>
        <div class="col-12 col-sm-6">
          <div class="text-subtitle2">Last backup time</div>
          <q-badge color="info" class="text-h6 q-pa-sm">
            {{ device.last_backup_time ? formatDateTime(device.last_backup_time) : 'Never' }}
          </q-badge>
        </div>
      </q-card-section>
    </q-card>

    <q-card>
      <q-card-section>
        <q-inner-loading :showing="loading" />
        <q-form v-if="!loading" class="device-form q-gutter-md" @submit="save">
          <q-toggle v-model="form.enabled" label="Backups enabled" :disable="!canModify" />

          <q-input
            v-model.trim="form.name"
            label="Device name"
            outlined
            :readonly="!canModify"
            :rules="[required('Name')]"
          />
          <q-input
            v-model.trim="form.ip_address"
            label="IP address"
            outlined
            :readonly="!canModify"
            :rules="[required('IP address')]"
          />
          <q-input v-model.trim="form.dns_name" label="DNS name (optional)" outlined :readonly="!canModify" />

          <q-select
            v-model="form.device_group"
            :options="groupOptions"
            option-value="id"
            option-label="name"
            emit-value
            map-options
            outlined
            label="Device group"
            :disable="!canModify"
            :rules="[required('Device group')]"
          />
          <q-select
            v-model="form.collection_group"
            :options="collectionGroups"
            option-value="id"
            option-label="name"
            emit-value
            map-options
            clearable
            outlined
            label="Collection group"
            hint="Which collectors back up this device. Backups cannot run without one."
            :disable="!canModify"
          />
          <q-select
            v-model="form.device_type"
            :options="deviceTypes"
            option-value="id"
            option-label="name"
            emit-value
            map-options
            outlined
            label="Device type"
            :disable="!canModify"
            :rules="[required('Device type')]"
          />
          <q-select
            v-model="form.manufacturer"
            :options="manufacturers"
            option-value="id"
            option-label="name"
            emit-value
            map-options
            clearable
            outlined
            label="Manufacturer (optional)"
            :disable="!canModify"
          />
          <q-select
            v-model="form.backup_method"
            :options="backupMethods"
            option-value="key"
            option-label="friendly_name"
            emit-value
            map-options
            outlined
            label="Backup method"
            :hint="backupMethods.length ? undefined : 'No approved collector offers a backup method yet (Admin Settings > Workers)'"
            :disable="!canModify"
            :rules="[required('Backup method')]"
            @update:model-value="onMethodChange"
          />
          <q-banner v-if="selectedMethod && selectedMethod.versions.length > 1" dense rounded class="bg-warning text-black">
            Collectors run different versions of this driver ({{ selectedMethod.versions.join(', ') }}); the form
            follows the newest.
          </q-banner>
          <DriverParamsForm
            v-model="form.driver_params"
            :schema="selectedMethod?.params_schema"
            :title="`${selectedMethod?.friendly_name ?? 'Driver'} settings`"
            :disable="!canModify"
          />
          <q-select
            v-model="form.credential"
            :options="credentials"
            option-value="id"
            option-label="name"
            emit-value
            map-options
            clearable
            outlined
            label="Credential"
            :disable="!canModify"
          />
          <q-select
            v-model="form.backup_location"
            :options="backupLocations"
            option-value="id"
            option-label="name"
            emit-value
            map-options
            clearable
            outlined
            label="Backup location"
            :disable="!canModify"
          />
          <q-select
            v-model="form.retention_policy"
            :options="retentionPolicies"
            option-value="id"
            option-label="name"
            emit-value
            map-options
            clearable
            outlined
            label="Retention policy"
            :disable="!canModify"
          />
          <q-select
            v-model="form.schedule"
            :options="schedules"
            option-value="id"
            option-label="name"
            emit-value
            map-options
            clearable
            outlined
            label="Backup schedule"
            hint="Leave empty to back up only on demand"
            :disable="!canModify"
          />

          <div class="row q-gutter-sm">
            <q-btn v-if="canModify" type="submit" color="primary" label="Save" :loading="saving" />
            <q-btn flat :label="canModify ? 'Cancel' : 'Back'" :to="{ name: 'devices' }" />
          </div>
        </q-form>
      </q-card-section>
    </q-card>
  </q-page>
</template>

<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'
import { useRoute, useRouter } from 'vue-router'

import {
  backupLocationsApi,
  backupMethodsApi,
  backupSchedulesApi,
  collectionGroupsApi,
  credentialsApi,
  deviceGroupsApi,
  devicesApi,
  deviceTypesApi,
  manufacturersApi,
  retentionPoliciesApi,
} from '@/api/endpoints'
import type {
  BackupLocation,
  BackupMethod,
  BackupSchedule,
  CollectionGroup,
  Credential,
  DeviceDetail,
  DeviceGroup,
  DeviceType,
  DeviceWrite,
  Manufacturer,
  RetentionPolicy,
} from '@/api/types'
import DriverParamsForm from '@/components/DriverParamsForm.vue'
import { useNotify } from '@/composables/useNotify'
import { useAuthStore } from '@/stores/auth'
import { formatDateTime } from '@/utils/datetime'
import { statusColor } from '@/utils/format'
import { keepKnown } from '@/utils/schema'

const route = useRoute()
const router = useRouter()
const auth = useAuthStore()
const notify = useNotify()

const deviceId = computed(() => (route.name === 'device-edit' ? Number(route.params.id) : null))
const isEdit = computed(() => deviceId.value !== null)

const device = ref<DeviceDetail | null>(null)
const form = ref<DeviceWrite>({
  name: '',
  ip_address: '',
  dns_name: '',
  device_type: null,
  manufacturer: null,
  backup_method: 'noop',
  driver_params: {},
  device_group: null,
  collection_group: null,
  enabled: true,
  retention_policy: null,
  backup_location: null,
  credential: null,
  schedule: null,
})
const loading = ref(true)
const saving = ref(false)

const deviceTypes = ref<DeviceType[]>([])
const manufacturers = ref<Manufacturer[]>([])
const backupMethods = ref<BackupMethod[]>([])
const credentials = ref<Credential[]>([])
const backupLocations = ref<BackupLocation[]>([])
const retentionPolicies = ref<RetentionPolicy[]>([])
const schedules = ref<BackupSchedule[]>([])
const deviceGroups = ref<DeviceGroup[]>([])
const collectionGroups = ref<CollectionGroup[]>([])

const selectedMethod = computed(() => backupMethods.value.find((method) => method.key === form.value.backup_method))

// A different driver keeps only the settings it also has.
function onMethodChange(key: string): void {
  const method = backupMethods.value.find((m) => m.key === key)
  form.value.driver_params = keepKnown(form.value.driver_params, method?.params_schema)
}

const canModify = computed(() => (device.value ? device.value.user_permissions.includes('modify') : true))
const title = computed(() => {
  if (!isEdit.value) return 'Add Device'
  return `${canModify.value ? 'Configure' : 'View'} ${device.value?.name ?? 'Device'}`
})

// Devices can only be placed in groups the user may modify (the current group
// is always listed so an existing device displays correctly).
const groupOptions = computed(() =>
  deviceGroups.value.filter(
    (group) =>
      auth.isAdmin || group.user_permissions.includes('modify') || group.id === device.value?.device_group?.id,
  ),
)

const required = (label: string) => (value: unknown) =>
  (value !== null && value !== undefined && value !== '') || `${label} is required`

function toForm(detail: DeviceDetail): DeviceWrite {
  return {
    name: detail.name,
    ip_address: detail.ip_address,
    dns_name: detail.dns_name,
    device_type: detail.device_type?.id ?? null,
    manufacturer: detail.manufacturer?.id ?? null,
    backup_method: detail.backup_method,
    driver_params: detail.driver_params,
    device_group: detail.device_group?.id ?? null,
    collection_group: detail.collection_group?.id ?? null,
    enabled: detail.enabled,
    retention_policy: detail.retention_policy,
    backup_location: detail.backup_location,
    credential: detail.credential,
    schedule: detail.schedule,
  }
}

async function save(): Promise<void> {
  saving.value = true
  try {
    if (deviceId.value !== null) {
      await devicesApi.update(deviceId.value, form.value)
    } else {
      await devicesApi.create(form.value)
    }
    notify.success('Device saved')
    await router.push({ name: 'devices' })
  } catch (error) {
    notify.error(error, 'Failed to save device')
  } finally {
    saving.value = false
  }
}

onMounted(async () => {
  try {
    const byName = <T extends { name: string }>(a: T, b: T) => a.name.localeCompare(b.name)
    const [types, makers, methods, creds, locations, policies, scheduleList, groups, collections, detail] = await Promise.all([
      deviceTypesApi.list(),
      manufacturersApi.list(),
      backupMethodsApi.list(),
      credentialsApi.list(),
      backupLocationsApi.list(),
      retentionPoliciesApi.list(),
      backupSchedulesApi.list(),
      deviceGroupsApi.list(),
      collectionGroupsApi.list(),
      deviceId.value !== null ? devicesApi.get(deviceId.value) : Promise.resolve(null),
    ])
    deviceTypes.value = types.sort(byName)
    manufacturers.value = makers.sort(byName)
    backupMethods.value = methods
    credentials.value = creds.sort(byName)
    backupLocations.value = locations.sort(byName)
    retentionPolicies.value = policies.sort(byName)
    schedules.value = scheduleList.sort(byName)
    deviceGroups.value = groups.sort(byName)
    collectionGroups.value = collections.sort(byName)
    if (detail) {
      device.value = detail
      form.value = toForm(detail)
    }
  } catch (error) {
    notify.error(error, 'Failed to load device')
  } finally {
    loading.value = false
  }
})
</script>

<style scoped>
.device-form > * {
  max-width: 60ch;
}
</style>
