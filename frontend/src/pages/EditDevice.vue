<template>
  <q-page class="q-pa-md">
    <div class="text-h4 q-mb-md">{{ isEdit ? 'Edit' : 'Add' }} Device</div>
    
    <q-card>
      <q-card-section>
        <q-form @submit="save" class="q-gutter-md">
          <q-input
            v-model="form.name"
            label="Device Name"
            outlined
            :rules="[val => !!val || 'Name is required']"
          />
          
          <div class="row q-col-gutter-md">
            <div class="col-12 col-md-6">
              <q-input
                v-model="form.ip_address"
                label="IP Address"
                outlined
                :rules="[val => !!val || 'IP Address is required']"
              />
            </div>
            <div class="col-12 col-md-6">
              <q-input
                v-model="form.dns_name"
                label="DNS Name (optional)"
                outlined
              />
            </div>
          </div>

          <div class="row q-col-gutter-md">
            <div class="col-12 col-md-6">
              <q-select
                v-model="form.device_type"
                :options="deviceTypes"
                option-label="name"
                option-value="id"
                label="Device Type"
                outlined
                emit-value
                map-options
                :rules="[val => !!val || 'Device Type is required']"
              />
            </div>
            <div class="col-12 col-md-6">
              <q-select
                v-model="form.manufacturer"
                :options="manufacturers"
                option-label="name"
                option-value="id"
                label="Manufacturer"
                outlined
                emit-value
                map-options
                :rules="[val => !!val || 'Manufacturer is required']"
              />
            </div>
          </div>

          <div class="row q-col-gutter-md">
            <div class="col-12 col-md-4">
              <q-select
                v-model="form.credential"
                :options="credentials"
                option-label="name"
                option-value="id"
                label="Credential"
                outlined
                emit-value
                map-options
                clearable
              />
            </div>
            <div class="col-12 col-md-4">
              <q-select
                v-model="form.backup_location"
                :options="backupLocations"
                option-label="name"
                option-value="id"
                label="Backup Location"
                outlined
                emit-value
                map-options
                clearable
              />
            </div>
            <div class="col-12 col-md-4">
              <q-select
                v-model="form.retention_policy"
                :options="retentionPolicies"
                option-label="name"
                option-value="id"
                label="Retention Policy"
                outlined
                emit-value
                map-options
                clearable
              />
            </div>
          </div>

          <q-select
            v-model="form.labels"
            :options="labels"
            option-label="name"
            option-value="id"
            label="Labels"
            outlined
            multiple
            emit-value
            map-options
            use-chips
          />

          <q-toggle
            v-model="form.enabled"
            label="Backups Enabled"
          />
          
          <div class="row q-gutter-sm">
            <q-btn 
              type="submit" 
              color="primary" 
              label="Save" 
            />
            <q-btn 
              flat 
              label="Cancel" 
              @click="$router.back()"
            />
          </div>
        </q-form>
      </q-card-section>
    </q-card>
  </q-page>
</template>

<script setup>
import { ref, onMounted } from 'vue'
import { useQuasar } from 'quasar'
import { useRouter, useRoute } from 'vue-router'
import api from '../services/api'

const $q = useQuasar()
const router = useRouter()
const route = useRoute()

const isEdit = ref(!!route.params.id && route.params.id !== 'new')
const form = ref({ 
  name: '', 
  ip_address: '', 
  dns_name: '',
  device_type: null,
  manufacturer: null,
  credential: null,
  backup_location: null,
  retention_policy: null,
  labels: [],
  enabled: true
})

const deviceTypes = ref([])
const manufacturers = ref([])
const credentials = ref([])
const backupLocations = ref([])
const retentionPolicies = ref([])
const labels = ref([])

async function loadData() {
  try {
    const [typesResp, mfgResp, credsResp, locsResp, polsResp, labelsResp] = await Promise.all([
      api.get('/api/device-types/'),
      api.get('/api/manufacturers/'),
      api.get('/api/credentials/'),
      api.get('/api/backup-locations/'),
      api.get('/api/retention-policies/'),
      api.get('/api/labels/')
    ])
    
    deviceTypes.value = typesResp.data
    manufacturers.value = mfgResp.data
    credentials.value = credsResp.data
    backupLocations.value = locsResp.data
    retentionPolicies.value = polsResp.data
    labels.value = labelsResp.data

    if (isEdit.value) {
      const response = await api.get(`/api/devices/${route.params.id}/`)
      form.value = response.data
    }
  } catch (error) {
    $q.notify({ type: 'negative', message: 'Failed to load data' })
  }
}

async function save() {
  try {
    if (isEdit.value) {
      await api.put(`/api/devices/${route.params.id}/`, form.value)
    } else {
      await api.post('/api/devices/', form.value)
    }
    $q.notify({
      type: 'positive',
      message: 'Device saved successfully'
    })
    router.push('/devices')
  } catch (error) {
    $q.notify({
      type: 'negative',
      message: 'Failed to save device'
    })
  }
}

onMounted(() => {
  loadData()
})
</script>
