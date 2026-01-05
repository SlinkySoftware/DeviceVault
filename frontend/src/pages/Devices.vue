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
      <template v-slot:body-cell-actions="props">
        <q-td :props="props">
          <q-btn 
            flat 
            dense 
            color="primary" 
            label="Edit" 
            :to="`/devices/${props.row.id}`"
          />
          <q-btn 
            flat 
            dense 
            color="primary" 
            label="Backups" 
            :to="`/devices/${props.row.id}/backups`"
          />
          <q-btn 
            flat 
            dense 
            :color="props.row.enabled ? 'negative' : 'positive'"
            :label="props.row.enabled ? 'Disable' : 'Enable'"
            @click="toggleEnabled(props.row)"
          />
        </q-td>
      </template>
    </q-table>
  </q-page>
</template>

<script setup>
import { ref, onMounted, computed } from 'vue'
import { useQuasar } from 'quasar'
import api from '../services/api'

const $q = useQuasar()
const devices = ref([])
const filter = ref({ manufacturer: '', type: '', status: 'All' })

const columns = [
  { name: 'name', label: 'Name', field: 'name', align: 'left', sortable: true },
  { name: 'ip_address', label: 'IP', field: 'ip_address', align: 'left' },
  { name: 'type', label: 'Type', field: row => row.device_type?.name || 'N/A', align: 'left' },
  { name: 'manufacturer', label: 'Manufacturer', field: row => row.manufacturer?.name || 'N/A', align: 'left' },
  { name: 'last_backup_time', label: 'Last Backup', field: 'last_backup_time', align: 'left' },
  { name: 'status', label: 'Status', field: 'last_backup_status', align: 'center' },
  { name: 'enabled', label: 'Enabled', field: 'enabled', align: 'center' },
  { name: 'actions', label: 'Actions', align: 'center' }
]

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

async function loadDevices() {
  try {
    const response = await api.get('/api/devices/')
    devices.value = response.data
  } catch (error) {
    $q.notify({ type: 'negative', message: 'Failed to fetch devices' })
  }
}

async function toggleEnabled(device) {
  try {
    await api.patch(`/api/devices/${device.id}/`, { enabled: !device.enabled })
    $q.notify({ 
      type: 'positive', 
      message: `Device ${device.enabled ? 'disabled' : 'enabled'}` 
    })
    loadDevices()
  } catch (error) {
    $q.notify({ type: 'negative', message: 'Failed to update device' })
  }
}

onMounted(() => {
  loadDevices()
})
</script>
