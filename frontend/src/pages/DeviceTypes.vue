<template>
  <q-page class="q-pa-md">
    <q-card>
      <q-card-section>
        <div class="row items-center q-mb-sm">
          <div class="col">
            <div class="text-h5">Device Types</div>
          </div>
          <div class="col-auto">
            <q-btn color="primary" label="Add Device Type" @click="showAddDialog" />
          </div>
        </div>
        <div class="row justify-end">
          <div class="text-caption text-grey">
            Manage device type categories and icons
          </div>
        </div>
      </q-card-section>
      <q-separator />

      <q-card-section>
        <q-table
      :rows="deviceTypes"
      :columns="columns"
      row-key="id"
      flat
      class="admin-table"
    >
      <template v-slot:body-cell-icon="props">
        <q-td :props="props">
          <q-icon :name="props.row.icon || 'router'" size="lg" color="primary" />
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
      <q-card style="min-width: 400px">
        <q-card-section>
          <div class="text-h6">{{ editMode ? 'Edit' : 'Add' }} Device Type</div>
        </q-card-section>
        <q-card-section>
          <q-input v-model="form.name" label="Name" outlined class="q-mb-md" />
          <div class="row items-center q-mb-md">
            <q-select
              v-model="form.icon"
              label="Icon"
              :options="commonIcons"
              outlined
              class="col"
              emit-value
              map-options
            >
              <template v-slot:prepend>
                <q-icon :name="form.icon || 'router'" />
              </template>
              <template v-slot:option="scope">
                <q-item v-bind="scope.itemProps">
                  <q-item-section avatar>
                    <q-icon :name="scope.opt" />
                  </q-item-section>
                  <q-item-section>
                    <q-item-label>{{ scope.opt }}</q-item-label>
                  </q-item-section>
                </q-item>
              </template>
            </q-select>
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
import { ref, onMounted } from 'vue'
import { useQuasar } from 'quasar'
import api from '../services/api'

const $q = useQuasar()
const deviceTypes = ref([])
const dialog = ref(false)
const editMode = ref(false)
const form = ref({ name: '' })

const columns = [
  { name: 'icon', label: 'Icon', field: 'icon', align: 'center' },
  { name: 'name', label: 'Name', field: 'name', align: 'left', sortable: true },
  { name: 'actions', label: 'Actions', align: 'right' }
]

const commonIcons = [
  'cloud',
  'computer',
  'dns',
  'router',
  'security',
  'shield',
  'storage',
  'vpn_lock',
  'wifi'
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
  form.value = { name: '', icon: 'router' }
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
