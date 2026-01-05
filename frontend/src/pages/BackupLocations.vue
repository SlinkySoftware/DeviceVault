<template>
  <q-page class="q-pa-md">
    <div class="row justify-between items-center q-mb-md">
      <div class="text-h4">Backup Locations</div>
      <q-btn color="primary" label="Add Location" @click="showAddDialog" />
    </div>

    <q-table
      :rows="locations"
      :columns="columns"
      row-key="id"
      flat
      bordered
    >
      <template v-slot:body-cell-actions="props">
        <q-td :props="props">
          <q-btn flat dense color="primary" icon="edit" @click="editItem(props.row)" />
          <q-btn flat dense color="negative" icon="delete" @click="deleteItem(props.row)" />
        </q-td>
      </template>
    </q-table>

    <q-dialog v-model="dialog">
      <q-card style="min-width: 500px">
        <q-card-section>
          <div class="text-h6">{{ editMode ? 'Edit' : 'Add' }} Backup Location</div>
        </q-card-section>
        <q-card-section class="q-gutter-md">
          <q-input v-model="form.name" label="Name" outlined />
          <q-select 
            v-model="form.location_type" 
            :options="locationTypes" 
            label="Location Type" 
            outlined
          />
          <div class="text-subtitle2 q-mb-sm">Configuration (JSON)</div>
          <q-input 
            v-model="configJson" 
            type="textarea" 
            outlined
            rows="8"
            hint="Enter location configuration as JSON"
          />
        </q-card-section>
        <q-card-actions align="right">
          <q-btn flat label="Cancel" v-close-popup />
          <q-btn color="primary" label="Save" @click="save" />
        </q-card-actions>
      </q-card>
    </q-dialog>
  </q-page>
</template>

<script setup>
import { ref, onMounted, computed } from 'vue'
import { useQuasar } from 'quasar'
import api from '../services/api'

const $q = useQuasar()
const locations = ref([])
const dialog = ref(false)
const editMode = ref(false)
const form = ref({ name: '', location_type: 'git', config: {} })

const locationTypes = ['git', 'filesystem', 's3', 'azure', 'gcs']

const configJson = computed({
  get: () => JSON.stringify(form.value.config || {}, null, 2),
  set: (val) => {
    try {
      form.value.config = JSON.parse(val)
    } catch (e) {
      // Invalid JSON
    }
  }
})

const columns = [
  { name: 'name', label: 'Name', field: 'name', align: 'left', sortable: true },
  { name: 'type', label: 'Type', field: 'location_type', align: 'left' },
  { name: 'actions', label: 'Actions', align: 'center' }
]

async function loadData() {
  try {
    const response = await api.get('/api/backup-locations/')
    locations.value = response.data
  } catch (error) {
    $q.notify({ type: 'negative', message: 'Failed to load locations' })
  }
}

function showAddDialog() {
  form.value = { name: '', location_type: 'git', config: {} }
  editMode.value = false
  dialog.value = true
}

function editItem(item) {
  form.value = { ...item }
  editMode.value = true
  dialog.value = true
}

async function save() {
  try {
    if (editMode.value) {
      await api.put(`/api/backup-locations/${form.value.id}/`, form.value)
    } else {
      await api.post('/api/backup-locations/', form.value)
    }
    $q.notify({ type: 'positive', message: 'Saved successfully' })
    dialog.value = false
    loadData()
  } catch (error) {
    $q.notify({ type: 'negative', message: 'Failed to save' })
  }
}

async function deleteItem(item) {
  $q.dialog({
    title: 'Confirm',
    message: `Delete location "${item.name}"?`,
    cancel: true
  }).onOk(async () => {
    try {
      await api.delete(`/api/backup-locations/${item.id}/`)
      $q.notify({ type: 'positive', message: 'Deleted successfully' })
      loadData()
    } catch (error) {
      $q.notify({ type: 'negative', message: 'Failed to delete' })
    }
  })
}

onMounted(() => {
  loadData()
})
</script>
