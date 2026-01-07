<template>
  <q-page class="q-pa-md">
    <div class="row justify-between items-center q-mb-md">
      <div class="text-h4">Credentials</div>
      <q-btn color="primary" label="Add Credential" @click="showAddDialog" />
    </div>

    <q-table
      :rows="credentials"
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
          <div class="text-h6">{{ editMode ? 'Edit' : 'Add' }} Credential</div>
        </q-card-section>
        <q-card-section class="q-gutter-md">
          <q-input v-model="form.name" label="Name" outlined />
          <q-select 
            v-model="form.credential_type" 
            :options="credentialTypes" 
            option-label="name"
            option-value="id"
            label="Credential Type" 
            outlined
            emit-value
            map-options
          />
          <div v-if="form.credential_type">
            <div class="text-subtitle2 q-mb-sm">Credential Data (JSON)</div>
            <q-input 
              v-model="dataJson" 
              type="textarea" 
              outlined
              rows="5"
              hint="Enter credential data as JSON"
            />
          </div>
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
const credentials = ref([])
const credentialTypes = ref([])
const dialog = ref(false)
const editMode = ref(false)
const form = ref({ name: '', credential_type: null, data: {} })

const dataJson = computed({
  get: () => JSON.stringify(form.value.data || {}, null, 2),
  set: (val) => {
    try {
      form.value.data = JSON.parse(val)
    } catch (e) {
      // Invalid JSON, keep old value
    }
  }
})

const columns = [
  { name: 'name', label: 'Name', field: 'name', align: 'left', sortable: true },
  { name: 'type', label: 'Type', field: 'credential_type', align: 'left' },
  { name: 'actions', label: 'Actions', align: 'center' }
]

async function loadData() {
  try {
    const [credsResp, typesResp] = await Promise.all([
      api.get('/credentials/'),
      api.get('/credential-types/')
    ])
    credentials.value = credsResp.data
    credentialTypes.value = typesResp.data
  } catch (error) {
    $q.notify({ type: 'negative', message: 'Failed to load credentials' })
  }
}

function showAddDialog() {
  form.value = { name: '', credential_type: null, data: {} }
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
      await api.put(`/credentials/${form.value.id}/`, form.value)
    } else {
      await api.post('/credentials/', form.value)
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
    message: `Delete credential "${item.name}"?`,
    cancel: true
  }).onOk(async () => {
    try {
      await api.delete(`/credentials/${item.id}/`)
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
