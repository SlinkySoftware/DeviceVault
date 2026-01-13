
<template>
  <q-page class="q-pa-md">
    <q-card>
      <q-card-section>
        <div class="row items-center q-mb-sm">
          <div class="col">
            <div class="text-h4">Collection Groups</div>
          </div>
          <div class="col-auto">
            <q-btn color="primary" label="Add Collection Group" @click="showAddDialog" />
          </div>
        </div>
        <div class="row justify-end">
          <div class="text-caption text-grey">
            Configure collection groups for device backup task distribution
          </div>
        </div>
      </q-card-section>
      <q-separator />

      <q-card-section>
        <q-table
      :rows="collectionGroups"
      :columns="columns"
      row-key="id"
      flat
    >
      <template v-slot:body-cell-device_count="props">
        <q-td :props="props">
          <q-badge color="info" :label="props.row.device_count" />
        </q-td>
      </template>
      <template v-slot:body-cell-actions="props">
        <q-td :props="props">
          <q-btn color="primary" icon="edit" label="Edit" @click="editItem(props.row)" class="q-mr-sm" />
          <q-btn 
            color="negative" 
            icon="delete" 
            label="Delete" 
            @click="deleteItem(props.row)"
            :disable="props.row.device_count > 0"
            class="q-mr-sm"
          />
        </q-td>
      </template>
    </q-table>
      </q-card-section>
    </q-card>

    <q-dialog v-model="dialog">
      <q-card style="min-width: 500px">
        <q-card-section>
          <div class="text-h6">{{ editMode ? 'Edit' : 'Add' }} Collection Group</div>
        </q-card-section>
        <q-card-section class="q-gutter-md">
          <q-input 
            v-model="form.name" 
            label="Name" 
            outlined
            :rules="[val => !!val || 'Name is required']"
          />
          <q-input 
            v-model="form.description" 
            label="Description" 
            outlined
            type="textarea"
            rows="4"
          />
          <q-input 
            v-model="form.rabbitmq_queue_id" 
            label="RabbitMQ Queue ID" 
            outlined
            :rules="[val => !!val || 'RabbitMQ Queue ID is required']"
            hint="Queue ID for task distribution to workers"
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
const collectionGroups = ref([])
const dialog = ref(false)
const editMode = ref(false)
const form = ref({ 
  name: '', 
  description: '', 
  rabbitmq_queue_id: '' 
})

const columns = [
  { name: 'name', label: 'Name', field: 'name', align: 'left', sortable: true },
  { name: 'description', label: 'Description', field: 'description', align: 'left' },
  { name: 'rabbitmq_queue_id', label: 'RabbitMQ Queue ID', field: 'rabbitmq_queue_id', align: 'left' },
  { name: 'device_count', label: 'Devices', field: 'device_count', align: 'center', sortable: true },
  { name: 'actions', label: 'Actions', align: 'right' }
]

async function loadData() {
  try {
    const response = await api.get('/collection-groups/')
    collectionGroups.value = response.data
  } catch (error) {
    console.error('Load error:', error)
    $q.notify({ type: 'negative', message: 'Failed to load collection groups' })
  }
}

function showAddDialog() {
  form.value = { name: '', description: '', rabbitmq_queue_id: '' }
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
      await api.put(`/collection-groups/${form.value.id}/`, form.value)
      $q.notify({ type: 'positive', message: 'Collection group updated successfully' })
    } else {
      await api.post('/collection-groups/', form.value)
      $q.notify({ type: 'positive', message: 'Collection group created successfully' })
    }
    dialog.value = false
    loadData()
  } catch (error) {
    console.error('Save error:', error)
    $q.notify({ type: 'negative', message: 'Failed to save collection group' })
  }
}

async function deleteItem(item) {
  if (item.device_count > 0) {
    $q.notify({ 
      type: 'negative', 
      message: `Cannot delete "${item.name}": ${item.device_count} device(s) assigned to this group` 
    })
    return
  }
  
  $q.dialog({
    title: 'Confirm Delete',
    message: `Delete collection group "${item.name}"?`,
    cancel: true
  }).onOk(async () => {
    try {
      await api.delete(`/collection-groups/${item.id}/`)
      $q.notify({ type: 'positive', message: 'Collection group deleted successfully' })
      loadData()
    } catch (error) {
      console.error('Delete error:', error)
      $q.notify({ type: 'negative', message: 'Failed to delete collection group' })
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
