<template>
  <q-page class="q-pa-md">
    <div class="text-h4 q-mb-md">{{ isEdit ? 'Configure' : 'Add' }} Device</div>
    
    <!-- Backup Status Box (only for existing devices) -->
    <q-card v-if="isEdit && form.name" class="q-mb-md" bordered>
      <q-card-section>
        <div class="text-h6 q-mb-sm">Backup Status</div>
        <div class="row q-col-gutter-md">
          <div class="col-12 col-md-6">
            <div class="text-subtitle2 q-mb-sm">Last Backup Status</div>
            <q-badge 
              :color="form.last_backup_status?.toLowerCase().includes('success') ? 'positive' : 'negative'"
              class="backup-status-badge"
            >
              {{ form.last_backup_status || 'Never backed up' }}
            </q-badge>
          </div>
          <div class="col-12 col-md-6">
            <div class="text-subtitle2 q-mb-sm">Last Backup Time</div>
            <q-badge 
              color="info"
              class="backup-time-badge"
            >
              {{ formatBackupTime(form.last_backup_time) }}
            </q-badge>
          </div>
        </div>
      </q-card-section>
    </q-card>
    
    <q-card>
      <q-card-section>
        <div class="row items-center justify-between q-mb-md">
          <div></div>
          <q-badge 
            :color="form.enabled ? 'positive' : 'negative'" 
            class="status-badge"
          >
            {{ form.enabled ? 'Enabled' : 'Disabled' }}
          </q-badge>
        </div>
        <q-form @submit="save" class="q-gutter-md form-grid">
          <!-- Enabled Toggle -->
          <q-toggle
            v-model="form.enabled"
            label="Backups Enabled"
            :color="form.enabled ? 'positive' : 'negative'"
            :disable="!canModify"
            class="enabled-toggle"
          />
          
          <!-- Device Name -->
          <q-input
            v-model="form.name"
            label="Device Name"
            outlined
            class="field-hostname"
            :rules="[val => !!val || 'Name is required']"
            :readonly="!canModify"
          />
          
          <!-- Device Group -->
          <q-select
            v-model="form.device_group"
            :options="deviceGroupOptions"
            option-label="name"
            option-value="id"
            label="Device Group"
            outlined
            emit-value
            map-options
            class="field-dropdown"
            :rules="[val => !!val || 'Device Group is required']"
            :disable="!canModify"
          />
          
          <!-- Device Type -->
          <q-select
            v-model="form.device_type"
            :options="deviceTypes"
            option-label="name"
            option-value="id"
            label="Device Type"
            outlined
            emit-value
            map-options
            class="field-dropdown"
            :rules="[val => !!val || 'Device Type is required']"
            :disable="!canModify"
          />
          
          <!-- IP Address -->
          <q-input
            v-model="form.ip_address"
            label="IP Address"
            outlined
            class="field-ip"
            :rules="[val => !!val || 'IP Address is required']"
            :readonly="!canModify"
          />
          
          <!-- DNS Name -->
          <q-input
            v-model="form.dns_name"
            label="DNS Name (optional)"
            outlined
            class="field-hostname"
            :readonly="!canModify"
          />
          
          <!-- Backup Method -->
          <q-select
            v-model="form.backup_method"
            :options="backupMethods"
            option-label="friendly_name"
            option-value="key"
            label="Backup Method"
            outlined
            emit-value
            map-options
            class="field-dropdown"
            :rules="[val => !!val || 'Backup Method is required']"
            :disable="!canModify"
          />
          
          <!-- Credential -->
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
            class="field-dropdown"
            :disable="!canModify"
          />
          
          <!-- Backup Location -->
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
            class="field-dropdown"
            :disable="!canModify"
          />
          
          <!-- Retention Policy -->
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
            class="field-dropdown"
            :disable="!canModify"
          />
          
          <div class="row q-gutter-sm">
            <q-btn 
              v-if="canModify"
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
import { ref, onMounted, computed } from 'vue'
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
  backup_method: 'noop',
  credential: null,
  backup_location: null,
  retention_policy: null,
  device_group: null,
  enabled: true,
  last_backup_status: null,
  last_backup_time: null
})
const canModify = ref(true)

const deviceTypes = ref([])
const backupMethods = ref([])
const credentials = ref([])
const backupLocations = ref([])
const retentionPolicies = ref([])
const deviceGroups = ref([])
const deviceGroupOptions = ref([])

const statusColor = computed(() => {
  const status = form.value.last_backup_status
  if (!status || status === 'Never backed up') return 'text-grey'
  if (status.toLowerCase().includes('success')) return 'text-positive'
  if (status.toLowerCase().includes('fail') || status.toLowerCase().includes('error')) return 'text-negative'
  return 'text-warning'
})

function formatBackupTime(time) {
  if (!time) return 'Never'
  return new Date(time).toLocaleString()
}

async function loadData() {
  try {
    const [typesResp, methodsResp, credsResp, locsResp, polsResp, groupsResp] = await Promise.all([
      api.get('/device-types/'),
      api.get('/backup-methods/'),
      api.get('/credentials/'),
      api.get('/backup-locations/'),
      api.get('/retention-policies/'),
      api.get('/device-groups/')
    ])
    
    deviceTypes.value = typesResp.data
    backupMethods.value = methodsResp.data
    credentials.value = credsResp.data
    backupLocations.value = locsResp.data
    retentionPolicies.value = polsResp.data
    deviceGroups.value = groupsResp.data || []
    
    // Filter device groups to only those user can modify (for new devices)
    // For editing, show all groups user has view/modify for (to see which group device belongs to)
    deviceGroupOptions.value = deviceGroups.value
      .filter(g => isEdit.value ? (g.user_permissions?.includes('view') || g.user_permissions?.includes('modify')) : g.user_permissions?.includes('modify'))
      .sort((a, b) => a.name.localeCompare(b.name))

    if (isEdit.value) {
      const response = await api.get(`/devices/${route.params.id}/`)
      const data = response.data || {}
      // Determine modify permission for read-only mode
      const perms = data.user_permissions || []
      canModify.value = perms.includes('modify')
      form.value = {
        name: data.name || '',
        ip_address: data.ip_address || '',
        dns_name: data.dns_name || '',
        device_type: data.device_type?.id ?? null,
        backup_method: data.backup_method ?? 'noop',
        credential: data.credential ?? null,
        backup_location: data.backup_location ?? null,
        retention_policy: data.retention_policy ?? null,
        device_group: data.device_group?.id ?? null,
        enabled: data.enabled ?? true,
        last_backup_status: data.last_backup_status ?? null,
        last_backup_time: data.last_backup_time ?? null
      }
    }
  } catch (error) {
    console.error('Load error:', error)
    $q.notify({ type: 'negative', message: 'Failed to load data' })
  }
}

async function save() {
  try {
    if (isEdit.value) {
      await api.put(`/devices/${route.params.id}/`, form.value)
    } else {
      await api.post('/devices/', form.value)
    }
    $q.notify({
      type: 'positive',
      message: 'Device saved successfully'
    })
    router.push('/devices')
  } catch (error) {
    console.error('Save error:', error)
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
<style scoped>
/* Status badge at top right */
.status-badge {
  font-size: 1.2rem;
  padding: 8px 16px;
  min-height: 2.5rem;
}

/* Backup status badges */
.backup-status-badge,
.backup-time-badge {
  font-size: 1.6rem;
  padding: 12px 20px;
  min-height: 3.5rem;
  display: inline-flex;
  align-items: center;
  justify-content: center;
}

/* Enabled toggle styling */
.enabled-toggle {
  margin-bottom: 0.5rem;
}

/* Form layout with dynamic field widths */
.form-grid {
  display: flex;
  flex-direction: column;
  gap: 1rem;
}

/* Device Name - max length for hostname is 63 chars, typically ~45-50ch width */
.field-hostname {
  max-width: 50ch;
}

/* IP Address - IPv4 (15 chars max) or IPv6 (45 chars max), use 45ch to be safe */
.field-ip {
  max-width: 45ch;
}

/* Dropdown fields - sized to content, max reasonable width of ~40ch */
.field-dropdown {
  max-width: min(100%, 50ch);
}
</style>