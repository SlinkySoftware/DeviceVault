<template>
  <q-page class="q-pa-md">
    <q-card>
      <q-card-section>
        <div class="row items-center q-mb-sm">
          <div class="col">
            <div class="text-h5">Credentials</div>
          </div>
          <div class="col-auto">
            <q-btn color="primary" label="Add Credential" @click="showAddDialog" />
          </div>
        </div>
        <div class="row justify-end">
          <div class="text-caption text-grey">
            Manage authentication credentials for device backups
          </div>
        </div>
      </q-card-section>
      <q-separator />

      <q-card-section>
        <q-table
      :rows="credentials"
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
  { name: 'actions', label: 'Actions', align: 'right' }
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
