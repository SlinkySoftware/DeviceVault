<template>
  <q-page class="q-pa-md">
    <q-card>
      <q-card-section>
        <div class="row items-center q-mb-sm">
          <div class="col">
            <div class="text-h5">Retention Policies</div>
          </div>
          <div class="col-auto">
            <q-btn color="primary" label="Add Policy" @click="showAddDialog" />
          </div>
        </div>
        <div class="row justify-end">
          <div class="text-caption text-grey">
            Define how long backups are retained before cleanup
          </div>
        </div>
      </q-card-section>
      <q-separator />

      <q-card-section>
        <q-table
      :rows="policies"
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
          <div class="text-h6">{{ editMode ? 'Edit' : 'Add' }} Retention Policy</div>
        </q-card-section>
        <q-card-section class="q-gutter-md">
          <q-input v-model="form.name" label="Name" outlined />
          <q-input 
            v-model.number="form.max_backups" 
            type="number" 
            label="Max Backups (optional)" 
            outlined
            clearable
          />
          <q-input 
            v-model.number="form.max_days" 
            type="number" 
            label="Max Days (optional)" 
            outlined
            clearable
          />
          <q-input 
            v-model.number="form.max_size_bytes" 
            type="number" 
            label="Max Size Bytes (optional)" 
            outlined
            clearable
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
import { ref, onMounted } from 'vue'
import { useQuasar } from 'quasar'
import api from '../services/api'

const $q = useQuasar()
const policies = ref([])
const dialog = ref(false)
const editMode = ref(false)
const form = ref({ name: '', max_backups: null, max_days: null, max_size_bytes: null })

const columns = [
  { name: 'name', label: 'Name', field: 'name', align: 'left', sortable: true },
  { name: 'max_backups', label: 'Max Backups', field: 'max_backups', align: 'left' },
  { name: 'max_days', label: 'Max Days', field: 'max_days', align: 'left' },
  { name: 'max_size', label: 'Max Size', field: 'max_size_bytes', align: 'left' },
  { name: 'actions', label: 'Actions', align: 'right' }
]

async function loadData() {
  try {
    const response = await api.get('/retention-policies/')
    policies.value = response.data
  } catch (error) {
    $q.notify({ type: 'negative', message: 'Failed to load policies' })
  }
}

function showAddDialog() {
  form.value = { name: '', max_backups: null, max_days: null, max_size_bytes: null }
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
      await api.put(`/retention-policies/${form.value.id}/`, form.value)
    } else {
      await api.post('/retention-policies/', form.value)
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
    message: `Delete policy "${item.name}"?`,
    cancel: true
  }).onOk(async () => {
    try {
      await api.delete(`/retention-policies/${item.id}/`)
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
