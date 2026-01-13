<template>
  <q-page class="q-pa-md">
    <div class="text-h5 q-mb-md">Theme Settings</div>
    
    <q-card>
      <q-card-section>
        <div class="text-subtitle1 q-mb-md">Customize Application Theme Colors</div>
        <div class="text-caption text-grey q-mb-md">
          Note: Only superusers can modify theme settings. Changes apply to all users.
        </div>
        
        <q-form @submit="saveSettings" class="q-gutter-md">
          <div class="row q-col-gutter-md">
            <div class="col-12 col-md-4">
              <q-input
                v-model="form.title_bar_color"
                label="Title Bar Color"
                outlined
                :rules="[val => /^#[0-9A-F]{6}$/i.test(val) || 'Invalid hex color']"
                :readonly="!isSuperuser"
              >
                <template v-slot:append>
                  <q-icon name="palette">
                    <q-popup-proxy cover transition-show="scale" transition-hide="scale">
                      <q-color v-model="form.title_bar_color" :disable="!isSuperuser" />
                    </q-popup-proxy>
                  </q-icon>
                </template>
                <template v-slot:prepend>
                  <div class="color-preview" :style="{ backgroundColor: form.title_bar_color }"></div>
                </template>
              </q-input>
            </div>
            
            <div class="col-12 col-md-4">
              <q-input
                v-model="form.dashboard_box_color"
                label="Card Border Color"
                outlined
                :rules="[val => /^#[0-9A-F]{6}$/i.test(val) || 'Invalid hex color']"
                :readonly="!isSuperuser"
              >
                <template v-slot:append>
                  <q-icon name="palette">
                    <q-popup-proxy cover transition-show="scale" transition-hide="scale">
                      <q-color v-model="form.dashboard_box_color" :disable="!isSuperuser" />
                    </q-popup-proxy>
                  </q-icon>
                </template>
                <template v-slot:prepend>
                  <div class="color-preview" :style="{ backgroundColor: form.dashboard_box_color }"></div>
                </template>
              </q-input>
            </div>
            
            <div class="col-12 col-md-4">
              <q-input
                v-model="form.dashboard_nested_box_color"
                label="Nested Box Border Color"
                outlined
                :rules="[val => /^#[0-9A-F]{6}$/i.test(val) || 'Invalid hex color']"
                :readonly="!isSuperuser"
              >
                <template v-slot:append>
                  <q-icon name="palette">
                    <q-popup-proxy cover transition-show="scale" transition-hide="scale">
                      <q-color v-model="form.dashboard_nested_box_color" :disable="!isSuperuser" />
                    </q-popup-proxy>
                  </q-icon>
                </template>
                <template v-slot:prepend>
                  <div class="color-preview" :style="{ backgroundColor: form.dashboard_nested_box_color }"></div>
                </template>
              </q-input>
            </div>
          </div>
          
          <div class="row q-gutter-sm">
            <q-btn 
              v-if="isSuperuser"
              type="submit" 
              color="primary" 
              label="Save Changes" 
              icon="save"
            />
            <q-btn 
              v-if="isSuperuser"
              flat 
              color="primary"
              label="Reset to Defaults" 
              icon="refresh"
              @click="resetToDefaults"
            />
          </div>
        </q-form>
      </q-card-section>
    </q-card>
    
    <q-card class="q-mt-md">
      <q-card-section>
        <div class="text-h6 q-mb-md">Preview</div>
        <div class="preview-container">
          <div class="preview-titlebar" :style="{ backgroundColor: form.title_bar_color }">
            <div class="text-white q-pa-sm">Application Title Bar</div>
          </div>
          <div class="preview-dashboard q-pa-md">
            <div class="preview-card-example" :style="{ borderColor: form.dashboard_box_color }">
              <div class="q-pa-md">
                <div class="q-mb-md text-weight-bold">Card with Border Color</div>
                <div class="preview-nested-box" :style="{ borderColor: form.dashboard_nested_box_color }">
                  <div class="q-pa-sm">Nested Box</div>
                </div>
              </div>
            </div>
          </div>
        </div>
      </q-card-section>
    </q-card>
  </q-page>
</template>

<script setup>
import { ref, onMounted, computed } from 'vue'
import { useQuasar } from 'quasar'
import api from '../services/api'

const $q = useQuasar()

const form = ref({
  title_bar_color: '#1976D2',
  dashboard_box_color: '#5b76d9',
  dashboard_nested_box_color: '#2196F3'
})

const userInfo = ref(null)

const isSuperuser = computed(() => {
  return userInfo.value?.is_superuser === true
})

async function loadUserInfo() {
  try {
    const response = await api.get('/auth/user/')
    userInfo.value = response.data
  } catch (error) {
    console.error('Failed to load user info:', error)
  }
}

async function loadSettings() {
  try {
    const response = await api.get('/theme-settings/')
    form.value = {
      title_bar_color: response.data.title_bar_color,
      dashboard_box_color: response.data.dashboard_box_color,
      dashboard_nested_box_color: response.data.dashboard_nested_box_color
    }
  } catch (error) {
    console.error('Failed to load theme settings:', error)
    $q.notify({
      type: 'negative',
      message: 'Failed to load theme settings'
    })
  }
}

async function saveSettings() {
  if (!isSuperuser.value) {
    $q.notify({
      type: 'warning',
      message: 'Only superusers can modify theme settings'
    })
    return
  }
  
  try {
    await api.put('/theme-settings/', form.value)
    
    // Immediately apply theme colors to the page
    document.documentElement.style.setProperty('--theme-title-bar', form.value.title_bar_color)
    document.documentElement.style.setProperty('--theme-dashboard-box', form.value.dashboard_box_color)
    document.documentElement.style.setProperty('--theme-dashboard-nested-box', form.value.dashboard_nested_box_color)
    
    $q.notify({
      type: 'positive',
      message: 'Theme settings saved successfully!'
    })
    
    // Emit event to update theme globally
    window.dispatchEvent(new CustomEvent('theme-updated', { detail: form.value }))
  } catch (error) {
    console.error('Failed to save theme settings:', error)
    $q.notify({
      type: 'negative',
      message: error.response?.data?.error || 'Failed to save theme settings'
    })
  }
}

function resetToDefaults() {
  form.value = {
    title_bar_color: '#1976D2',
    dashboard_box_color: '#1976D2',
    dashboard_nested_box_color: '#2196F3'
  }
}

onMounted(() => {
  loadUserInfo()
  loadSettings()
})
</script>

<style scoped>
.color-preview {
  width: 24px;
  height: 24px;
  border-radius: 4px;
  border: 1px solid rgba(255, 255, 255, 0.3);
}

.preview-container {
  border: 1px solid rgba(255, 255, 255, 0.1);
  border-radius: 8px;
  overflow: hidden;
}

.preview-titlebar {
  height: 50px;
  display: flex;
  align-items: center;
  padding: 0 16px;
}

.preview-dashboard {
  background: #1e1e1e;
  min-height: 200px;
}

.preview-box {
  border-radius: 8px;
  min-height: 150px;
}

.preview-card-example {
  border: 2px solid;
  border-radius: 8px;
  background: rgba(255, 255, 255, 0.05);
  min-height: 150px;
}

.preview-nested-box {
  border-radius: 4px;
  border: 3px solid;
  background: rgba(255, 255, 255, 0.02);
}
</style>
