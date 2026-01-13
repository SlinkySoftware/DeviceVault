<template>
  <q-page class="q-pa-md">
    <q-card>
      <q-card-section>
        <div class="row items-center q-mb-sm">
          <div class="col">
            <div class="text-h4">Backup Methods</div>
          </div>
        </div>
        <div class="row justify-end">
          <div class="text-caption text-grey">
            Available backup method plugins (read-only)
          </div>
        </div>
      </q-card-section>
      <q-separator />

      <q-card-section>
        <q-table
      :rows="backupMethods"
      :columns="columns"
      row-key="key"
      flat
    >
      <template v-slot:body-cell-friendly_name="props">
        <q-td :props="props">
          <strong>{{ props.row.friendly_name }}</strong>
        </q-td>
      </template>
    </q-table>
      </q-card-section>
    </q-card>
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

<style scoped>
:deep(.q-table) {
  font-size: 1.5rem;
}

:deep(.q-table tbody td) {
  padding: 12px 8px;
  font-size: 1.4rem;
}

:deep(.q-table thead th) {
  font-size: 1.5rem;
  font-weight: 600;
}

:deep(.q-table .q-badge) {
  font-size: 1.2rem;
  padding: 6px 12px;
  min-height: 2.5rem;
  display: inline-flex;
  align-items: center;
  justify-content: center;
}
</style>
