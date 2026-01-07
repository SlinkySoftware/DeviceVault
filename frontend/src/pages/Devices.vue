<template>
  <q-page class="q-pa-md">
    <div class="row justify-between items-center q-mb-md">
      <div class="text-h4">Devices</div>
      <q-btn color="primary" label="Add Device" @click="$router.push('/devices/new')" />
    </div>
    
    <div class="row q-col-gutter-md q-mb-md">
      <div class="col-12 col-md-4">
        <q-input 
          v-model="filter.manufacturer" 
          outlined 
          label="Manufacturer"
          clearable
        />
      </div>
      <div class="col-12 col-md-4">
        <q-input 
          v-model="filter.type" 
          outlined 
          label="Type"
          clearable
        />
      </div>
      <div class="col-12 col-md-4">
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
    >
      <template v-slot:body-cell-type="props">
        <q-td :props="props">
          <q-icon :name="props.row.device_type?.icon || 'router'" size="md" color="primary" class="q-mr-sm" />
          <span>{{ props.row.device_type?.name || 'N/A' }}</span>
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
            flat 
            dense 
            color="primary" 
            icon="edit"
            label="Edit"
            :to="`/devices/${props.row.id}`"
            class="q-mr-sm"
          />
          <q-btn 
            flat 
            dense 
            color="primary" 
            icon="visibility"
            label="Backups"
            :to="`/devices/${props.row.id}/backups`"
            class="q-mr-sm"
          />
          <q-btn 
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
 * Devices Page Component
 * 
 * Displays list of all network devices with filtering, sorting, and action buttons.
 * Allows users to:
 * - View all devices in tabular format
 * - Filter by manufacturer, type, and backup status
 * - Edit device details
 * - View device backup history
 * - Enable/disable devices for backups
 */

import { ref, onMounted, computed } from 'vue'
import { useQuasar } from 'quasar'
import api from '../services/api'

// ===== Component State =====

/** Quasar dialog and notification service */
const $q = useQuasar()

/** Array of device objects from API, contains all device data */
const devices = ref([])

/** Filter state object for search/filtering
 * Properties:
 * - manufacturer: Filter by manufacturer name
 * - type: Filter by device type name
 * - status: Filter by last backup status (All, success, failed)
 */
const filter = ref({ manufacturer: '', type: '', status: 'All' })

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
  { name: 'manufacturer', label: 'Manufacturer', field: row => row.manufacturer?.name || 'N/A', align: 'left' },
  { name: 'last_backup_time', label: 'Last Backup', field: 'last_backup_time', align: 'left' },
  { name: 'status', label: 'Status', field: 'last_backup_status', align: 'center' },
  { name: 'is_example_data', label: 'Example', field: 'is_example_data', align: 'center' },
  { name: 'enabled', label: 'Enabled', field: 'enabled', align: 'center' },
  { name: 'actions', label: 'Actions', align: 'center' }
]

// ===== Computed Properties =====

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
    if (filter.value.manufacturer && !d.manufacturer?.name?.toLowerCase().includes(filter.value.manufacturer.toLowerCase())) {
      return false
    }
    if (filter.value.type && !d.device_type?.name?.toLowerCase().includes(filter.value.type.toLowerCase())) {
      return false
    }
    if (filter.value.status && filter.value.status !== 'All' && d.last_backup_status !== filter.value.status) {
      return false
    }
    return true
  })
})

// ===== API Functions =====

/**
 * Load all devices from API
 * 
 * Fetches complete device list including:
 * - Device names, IPs, DNS names
 * - Device type and manufacturer references
 * - Backup status and timestamps
 * - Enabled/disabled state
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
  loadDevices()
})
</script>
