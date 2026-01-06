<template>
  <q-page class="q-pa-md">
    <div class="row justify-between items-center q-mb-md">
      <div class="text-h4">Device Types</div>
      <q-btn color="primary" label="Add Device Type" @click="showAddDialog" />
    </div>

    <q-table
      :rows="deviceTypes"
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
      <q-card style="min-width: 400px">
        <q-card-section>
          <div class="text-h6">{{ editMode ? 'Edit' : 'Add' }} Device Type</div>
        </q-card-section>
        <q-card-section>
          <q-input v-model="form.name" label="Name" outlined />
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
const deviceTypes = ref([])
const dialog = ref(false)
const editMode = ref(false)
const form = ref({ name: '' })

const columns = [
  { name: 'name', label: 'Name', field: 'name', align: 'left', sortable: true },
  { name: 'actions', label: 'Actions', align: 'center' }
]

async function loadData() {
  try {
    const response = await api.get('/device-types/')
    deviceTypes.value = response.data
  } catch (error) {
    $q.notify({ type: 'negative', message: 'Failed to load device types' })
  }
}

function showAddDialog() {
  form.value = { name: '' }
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
      await api.put(`/device-types/${form.value.id}/`, form.value)
    } else {
      await api.post('/device-types/', form.value)
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
    message: `Delete device type "${item.name}"?`,
    cancel: true
  }).onOk(async () => {
    try {
      await api.delete(`/device-types/${item.id}/`)
      $q.notify({ type: 'positive', message: 'Deleted successfully' })
      loadData()
    } catch (error) {
      $q.notify({ type: 'negative', message: 'Failed to delete (may be in use)' })
    }
  })
}

onMounted(() => {
  loadData()
})
</script>
