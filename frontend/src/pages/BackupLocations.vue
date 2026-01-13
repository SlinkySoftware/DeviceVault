<template>
  <q-page class="q-pa-md">
    <q-card>
      <q-card-section>
        <div class="row items-center q-mb-sm">
          <div class="col">
            <div class="text-h5">Backup Locations</div>
          </div>
          <div class="col-auto">
            <q-btn color="primary" label="Add Location" @click="showAddDialog" />
          </div>
        </div>
        <div class="row justify-end">
          <div class="text-caption text-grey">
            Configure storage locations for device backups
          </div>
        </div>
      </q-card-section>
      <q-separator />

      <q-card-section>
        <q-table
      :rows="locations"
      :columns="columns"
      row-key="id"
      flat
      class="admin-table"
    >
      <template v-slot:body-cell-name="props">
        <q-td :props="props">
          <strong>{{ props.row.name }}</strong>
        </q-td>
      </template>
      <template v-slot:body-cell-actions="props">
        <q-td :props="props">
          <q-btn color="primary" icon="edit" label="Edit" @click="editItem(props.row)" class="q-mr-sm" />
          <q-btn color="negative" icon="delete" label="Delete" @click="deleteItem(props.row)" class="q-mr-sm" />
        </q-td>
      </template>
    </q-table>
      </q-card-section>
    </q-card>

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
  { name: 'actions', label: 'Actions', align: 'right' }
]

async function loadData() {
  try {
    const response = await api.get('/backup-locations/')
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
      await api.put(`/backup-locations/${form.value.id}/`, form.value)
    } else {
      await api.post('/backup-locations/', form.value)
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
      await api.delete(`/backup-locations/${item.id}/`)
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
