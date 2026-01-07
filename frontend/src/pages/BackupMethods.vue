<template>
  <q-page class="q-pa-md">
    <div class="row justify-between items-center q-mb-md">
      <div class="text-h4">Backup Methods</div>
    </div>

    <q-table
      :rows="backupMethods"
      :columns="columns"
      row-key="key"
      flat
      bordered
    >
      <template v-slot:body-cell-friendly_name="props">
        <q-td :props="props">
          <strong>{{ props.row.friendly_name }}</strong>
        </q-td>
      </template>
    </q-table>
  </q-page>
</template>

<script setup>
/**
 * Backup Methods Page Component
 * 
 * Displays read-only list of all available backup method plugins.
 * Shows the friendly name and description of each plugin discovered
 * by the backend.
 */

import { ref, onMounted } from 'vue'
import { useQuasar } from 'quasar'
import api from '../services/api'

const $q = useQuasar()
const backupMethods = ref([])

const columns = [
  { name: 'friendly_name', label: 'Backup Method', field: 'friendly_name', align: 'left', sortable: true },
  { name: 'description', label: 'Description', field: 'description', align: 'left' }
]

async function loadData() {
  try {
    const response = await api.get('/backup-methods/')
    backupMethods.value = response.data
  } catch (error) {
    $q.notify({ type: 'negative', message: 'Failed to load backup methods' })
  }
}

onMounted(() => {
  loadData()
})
</script>
