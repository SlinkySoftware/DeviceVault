<template>
  <q-page class="q-pa-md">
    <div class="row justify-between items-center q-mb-md">
      <div class="text-h4">Manufacturers</div>
      <q-btn color="primary" label="Add Manufacturer" @click="showAddDialog" />
    </div>

    <q-table
      :rows="manufacturers"
      :columns="columns"
      row-key="id"
      flat
    >
      <template v-slot:body-cell-actions="props">
        <q-td :props="props">
          <q-btn color="primary" icon="edit" label="Edit" @click="editItem(props.row)" class="q-mr-sm" />
          <q-btn color="negative" icon="delete" label="Delete" @click="deleteItem(props.row)" class="q-mr-sm" />
        </q-td>
      </template>
    </q-table>

    <q-dialog v-model="dialog">
      <q-card style="min-width: 400px">
        <q-card-section>
          <div class="text-h6">{{ editMode ? 'Edit' : 'Add' }} Manufacturer</div>
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
const manufacturers = ref([])
const dialog = ref(false)
const editMode = ref(false)
const form = ref({ name: '' })

const columns = [
  { name: 'name', label: 'Name', field: 'name', align: 'left', sortable: true },
  { name: 'actions', label: 'Actions', align: 'right' }
]

async function loadData() {
  try {
    const response = await api.get('/manufacturers/')
    manufacturers.value = response.data
  } catch (error) {
    $q.notify({ type: 'negative', message: 'Failed to load manufacturers' })
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
      await api.put(`/manufacturers/${form.value.id}/`, form.value)
    } else {
      await api.post('/manufacturers/', form.value)
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
    message: `Delete manufacturer "${item.name}"?`,
    cancel: true
  }).onOk(async () => {
    try {
      await api.delete(`/manufacturers/${item.id}/`)
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
