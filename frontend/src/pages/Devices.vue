<template>
  <q-page class="q-pa-md">
    <div class="row justify-between items-center q-mb-md">
      <div class="text-h4">Devices</div>
      <q-btn 
        v-if="canAddDevice" 
        color="primary" 
        label="Add Device" 
        @click="$router.push('/devices/new')" 
      />
    </div>
    
    <div class="row q-col-gutter-md q-mb-md">
      <div class="col-12 col-md-3">
        <q-input 
          v-model="filter.name" 
          outlined 
          label="Name"
          clearable
        />
      </div>
      <div class="col-12 col-md-3">
        <q-select
          v-model="filter.type"
          :options="deviceTypes"
          option-value="id"
          option-label="name"
          outlined
          label="Device Type"
          clearable
          emit-value
          map-options
        />
      </div>
      <div class="col-12 col-md-3">
        <q-select
          v-model="filter.device_group"
          :options="deviceGroups"
          option-value="id"
          option-label="name"
          outlined
          label="Device Group"
          clearable
          emit-value
          map-options
        />
      </div>
      <div class="col-12 col-md-3">
        <q-select
          v-model="filter.status"
          :options="['All', 'success', 'failed']"
          outlined
          label="Status"
          clearable
        />
      </div>
    </div>

    <q-table
      :rows="filteredDevices"
      :columns="columns"
      row-key="id"
      flat
      bordered
      class="device-table"
    >
      <template v-slot:body-cell-type="props">
        <q-td :props="props">
          <q-icon :name="props.row.device_type?.icon || 'router'" size="md" color="primary" class="q-mr-sm" />
          <span>{{ props.row.device_type?.name || 'N/A' }}</span>
        </q-td>
      </template>
      <template v-slot:body-cell-device_group="props">
        <q-td :props="props">
          <q-badge color="info" outline>
            {{ props.row.device_group_name || props.row.device_group?.name || 'Unassigned' }}
          </q-badge>
        </q-td>
      </template>
      <template v-slot:body-cell-enabled="props">
        <q-td :props="props">
          <q-badge :color="props.row.enabled ? 'positive' : 'grey'">
            {{ props.row.enabled ? 'Enabled' : 'Disabled' }}
          </q-badge>
        </q-td>
      </template>
      <template v-slot:body-cell-status="props">
        <q-td :props="props">
          <q-badge :color="props.row.last_backup_status === 'success' ? 'positive' : 'negative'">
            {{ props.row.last_backup_status || 'N/A' }}
          </q-badge>
        </q-td>
      </template>
      <template v-slot:body-cell-is_example_data="props">
        <q-td :props="props">
          <q-badge :color="props.row.is_example_data ? 'warning' : 'grey'">
            {{ props.row.is_example_data ? 'Yes' : 'No' }}
          </q-badge>
        </q-td>
      </template>
      <template v-slot:body-cell-actions="props">
        <q-td :props="props">
          <q-btn 
            v-if="canEditDevice(props.row)"
            flat 
            dense 
            color="primary" 
            icon="edit"
            label="Edit"
            :to="`/devices/${props.row.id}`"
            class="q-mr-sm"
          />
          <q-btn 
            v-if="canViewBackups(props.row)"
            flat 
            dense 
            color="primary" 
            icon="visibility"
            label="Backups"
            :to="`/devices/${props.row.id}/backups`"
            class="q-mr-sm"
          />
          <q-btn 
            v-if="canEnableDevice(props.row)"
            flat 
            dense 
            :color="props.row.enabled ? 'negative' : 'positive'"
            :icon="props.row.enabled ? 'toggle_on' : 'toggle_off'"
            :label="props.row.enabled ? 'Disable' : 'Enable'"
            @click="toggleEnabled(props.row)"
          />
        </q-td>
      </template>
    </q-table>
  </q-page>
</template>

<script setup>
/**
 * Devices Page Component with RBAC Support
 * 
 * Displays list of devices with permission-based action visibility.
 * Users only see devices in device groups they have access to.
 * Action buttons are shown based on device group permissions:
 * - Add Device: Shown if user has 'add_device' in any group
 * - Edit: Shown if user has 'edit_configuration' for device's group
 * - View Backups: Shown if user has 'view_backups' for device's group
 * - Enable/Disable: Shown if user has 'enable_device' for device's group
 */

import { ref, onMounted, computed } from 'vue'
import { useQuasar } from 'quasar'
import api from '../services/api'

// ===== Component State =====

/** Quasar dialog and notification service */
const $q = useQuasar()

/** Array of device objects from API, includes user_permissions for each device */
const devices = ref([])

/** Array of device group objects for filter dropdown */
const deviceGroups = ref([])
const deviceTypes = ref([])

/** Filter state object for search/filtering
 * Properties:
 * - name: Filter by device name
 * - type: Filter by device type name
 * - device_group: Filter by device group name
 * - status: Filter by last backup status (All, success, failed)
 */
const filter = ref({ name: '', type: null, device_group: '', status: 'All' })

/**
 * Table Column Configuration
 * 
 * Defines columns displayed in device table including:
 * - name, ip_address, type, manufacturer
 * - last_backup_time, status, is_example_data, enabled
 * - actions (Edit, Backups, Enable/Disable)
 * 
 * Properties:
 * - name: Unique column identifier
 * - label: Display header text
 * - field: Property path or function to extract data
 * - align: Text alignment (left, center, right)
 * - sortable: Whether column can be sorted
 */
const columns = [
  { name: 'name', label: 'Name', field: 'name', align: 'left', sortable: true },
  { name: 'ip_address', label: 'IP', field: 'ip_address', align: 'left' },
  { name: 'type', label: 'Type', field: row => row.device_type?.name || '', align: 'left', sortable: true },
  { name: 'backup_method', label: 'Backup Method', field: 'backup_method_display', align: 'left', sortable: true },
  { name: 'device_group', label: 'Device Group', field: row => row.device_group_name || row.device_group?.name || 'N/A', align: 'left', sortable: true },
  { name: 'last_backup_time', label: 'Last Backup', field: 'last_backup_time', align: 'left' },
  { name: 'status', label: 'Status', field: 'last_backup_status', align: 'center' },
  { name: 'is_example_data', label: 'Example', field: 'is_example_data', align: 'center' },
  { name: 'enabled', label: 'Enabled', field: 'enabled', align: 'center' },
  { name: 'actions', label: 'Actions', align: 'center' }
]

// ===== Computed Properties =====

/**
 * Check if user can add devices
 * Shown if user has 'add_device' permission in at least one device group
 */
const canAddDevice = computed(() => {
  return devices.value.some(d => d.user_permissions && d.user_permissions.includes('add_device'))
})

/**
 * Computed: Filter devices based on current filter state
 * 
 * Filters applied in order:
 * 1. Manufacturer name contains filter value
 * 2. Device type name contains filter value
 * 3. Backup status matches selected status
 * 
 * Returns:
 * - Array of device objects matching all active filters
 */
const filteredDevices = computed(() => {
  return devices.value.filter(d => {
    if (filter.value.name && !d.name?.toLowerCase().includes(filter.value.name.toLowerCase())) {
      return false
    }
    if (filter.value.type) {
      const deviceTypeId = typeof d.device_type === 'object' ? d.device_type?.id : d.device_type
      if (deviceTypeId !== filter.value.type) {
        return false
      }
    }
    if (filter.value.device_group) {
      const deviceGroupId = typeof d.device_group === 'object' ? d.device_group?.id : d.device_group
      if (deviceGroupId !== filter.value.device_group) {
        return false
      }
    }
    if (filter.value.status && filter.value.status !== 'All' && d.last_backup_status !== filter.value.status) {
      return false
    }
    return true
  })
})

// ===== Permission Check Methods =====

/**
 * Check if user can edit a device based on device group permissions
 * 
 * Input:
 * - device (Object): Device object with user_permissions array
 * 
 * Returns:
 * - true if user has 'edit_configuration' permission for device's group
 */
function canEditDevice(device) {
  return device.user_permissions && device.user_permissions.includes('edit_configuration')
}

/**
 * Check if user can view backups for a device
 * 
 * Input:
 * - device (Object): Device object with user_permissions array
 * 
 * Returns:
 * - true if user has 'view_backups' permission for device's group
 */
function canViewBackups(device) {
  return device.user_permissions && device.user_permissions.includes('view_backups')
}

/**
 * Check if user can enable/disable a device
 * 
 * Input:
 * - device (Object): Device object with user_permissions array
 * 
 * Returns:
 * - true if user has 'enable_device' permission for device's group
 */
function canEnableDevice(device) {
  return device.user_permissions && device.user_permissions.includes('enable_device')
}

// ===== API Functions =====

/**
 * Load device groups for filter dropdown
 * Fetches all device groups and sorts them alphabetically
 */
async function loadDeviceGroups() {
  try {
    const response = await api.get('/device-groups/')
    deviceGroups.value = response.data.sort((a, b) => a.name.localeCompare(b.name))
  } catch (error) {
    $q.notify({ type: 'negative', message: 'Failed to fetch device groups' })
  }
}

/**
 * Load device types for the type filter dropdown
 */
async function loadDeviceTypes() {
  try {
    const response = await api.get('/device-types/')
    deviceTypes.value = (response.data || []).sort((a, b) => a.name.localeCompare(b.name))
  } catch (error) {
    $q.notify({ type: 'negative', message: 'Failed to fetch device types' })
  }
}

/**
 * Load all accessible devices from API
 * 
 * API automatically filters to only accessible device groups
 * and includes user_permissions for each device
 * 
 * Fetches complete device list including:
 * - Device names, IPs, DNS names
 * - Device type and manufacturer references
 * - Backup status and timestamps
 * - Enabled/disabled state
 * - user_permissions array with permission codes
 * 
 * Error handling:
 * - Catches API errors and displays notification
 */
async function loadDevices() {
  try {
    const response = await api.get('/devices/')
    devices.value = response.data
  } catch (error) {
    $q.notify({ type: 'negative', message: 'Failed to fetch devices' })
  }
}

/**
 * Toggle device enabled/disabled status
 * 
 * Input:
 * - device (Object): Device object to toggle
 * 
 * Process:
 * 1. Send PATCH request to API to toggle enabled flag
 * 2. Show success notification
 * 3. Reload devices list
 * 
 * Error handling:
 * - Catches API errors and displays notification
 */
async function toggleEnabled(device) {
  try {
    await api.patch(`/devices/${device.id}/`, { enabled: !device.enabled })
    $q.notify({ 
      type: 'positive', 
      message: `Device ${device.enabled ? 'disabled' : 'enabled'}` 
    })
    loadDevices()
  } catch (error) {
    $q.notify({ type: 'negative', message: 'Failed to update device' })
  }
}

// ===== Lifecycle Hooks =====

/**
 * Component mounted lifecycle hook
 * Executes once when component is mounted to DOM
 * Loads initial device data
 */
onMounted(() => {
  loadDeviceGroups()
  loadDeviceTypes()
  loadDevices()
})
</script>

<style scoped>
.device-table {
  font-size: 1.1rem;
}

:deep(.device-table tbody td) {
  padding: 12px 8px;
  font-size: 1.05rem;
}

:deep(.device-table thead th) {
  font-size: 1.1rem;
  font-weight: 600;
}
</style>
