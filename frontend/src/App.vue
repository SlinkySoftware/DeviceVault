<template>
  <q-layout view="hHh lpR fFf">
    <q-header v-if="!isLoginRoute" elevated class="bg-primary text-white">
      <q-toolbar>
        <q-toolbar-title class="row items-center no-wrap">
          <img src="/logos/dv-mini-logo.png" alt="DeviceVault" class="logo-mini q-mr-sm" />
          <span>DeviceVault</span>
        </q-toolbar-title>
        <q-space />
        <q-btn-dropdown v-if="isAuthenticated" flat dense icon="person" :label="userLabel">
          <q-list style="min-width: 180px">
            <q-item clickable to="/profile">
              <q-item-section avatar>
                <q-icon name="account_circle" />
              </q-item-section>
              <q-item-section>
                <q-item-label>Profile</q-item-label>
              </q-item-section>
            </q-item>
            <q-separator />
            <q-item clickable @click="logout">
              <q-item-section avatar>
                <q-icon name="logout" />
              </q-item-section>
              <q-item-section>
                <q-item-label>Logout</q-item-label>
              </q-item-section>
            </q-item>
          </q-list>
        </q-btn-dropdown>
      </q-toolbar>
    </q-header>

    <q-drawer v-if="!isLoginRoute" show-if-above side="left" bordered>
      <q-list>
        <q-item clickable to="/" exact>
          <q-item-section avatar>
            <q-icon name="dashboard" />
          </q-item-section>
          <q-item-section>
            <q-item-label>Dashboard</q-item-label>
          </q-item-section>
        </q-item>

        <q-item clickable to="/devices">
          <q-item-section avatar>
            <q-icon name="devices" />
          </q-item-section>
          <q-item-section>
            <q-item-label>Devices</q-item-label>
          </q-item-section>
        </q-item>

        <q-separator v-if="isAdmin" class="q-my-sm" />
        
        <q-item-label v-if="isAdmin" header class="text-grey-8">Admin Settings</q-item-label>
        
        <q-item v-if="isAdmin" clickable to="/vaultadmin/device-types">
          <q-item-section avatar>
            <q-icon name="category" />
          </q-item-section>
          <q-item-section>
            <q-item-label>Device Types</q-item-label>
          </q-item-section>
        </q-item>

        <q-item v-if="isAdmin" clickable to="/vaultadmin/manufacturers">
          <q-item-section avatar>
            <q-icon name="business" />
          </q-item-section>
          <q-item-section>
            <q-item-label>Manufacturers</q-item-label>
          </q-item-section>
        </q-item>

        <q-item v-if="isAdmin" clickable to="/vaultadmin/credentials">
          <q-item-section avatar>
            <q-icon name="vpn_key" />
          </q-item-section>
          <q-item-section>
            <q-item-label>Credentials</q-item-label>
          </q-item-section>
        </q-item>

        <q-item v-if="isAdmin" clickable to="/vaultadmin/backup-locations">
          <q-item-section avatar>
            <q-icon name="folder" />
          </q-item-section>
          <q-item-section>
            <q-item-label>Backup Locations</q-item-label>
          </q-item-section>
        </q-item>

        <q-item v-if="isAdmin" clickable to="/vaultadmin/retention-policies">
          <q-item-section avatar>
            <q-icon name="schedule" />
          </q-item-section>
          <q-item-section>
            <q-item-label>Retention Policies</q-item-label>
          </q-item-section>
        </q-item>

        <q-item v-if="isAdmin" clickable to="/vaultadmin/users">
          <q-item-section avatar>
            <q-icon name="people" />
          </q-item-section>
          <q-item-section>
            <q-item-label>Users</q-item-label>
          </q-item-section>
        </q-item>
      </q-list>
    </q-drawer>

    <q-page-container>
      <router-view />
    </q-page-container>
  </q-layout>
</template>

<script setup>
import { ref, computed, onMounted } from 'vue'
import { useRouter, useRoute } from 'vue-router'
import { watch } from 'vue'
import { useQuasar } from 'quasar'
import api from './services/api'

const $q = useQuasar()
const router = useRouter()
const route = useRoute()

const isAdmin = ref(true)
const isAuthenticated = ref(!!localStorage.getItem('authToken'))
const user = ref(null)
const userLabel = computed(() => user.value?.username || 'Account')
const isLoginRoute = computed(() => route.path === '/login')

const logout = async () => {
  try {
    await api.post('/auth/logout/')
  } catch (e) {
    // ignore errors, still clear client state
  }
  localStorage.removeItem('authToken')
  localStorage.removeItem('user')
  isAuthenticated.value = false
  $q.notify({ type: 'info', message: 'Logged out', position: 'top' })
  router.push('/login')
}

const syncAuth = async () => {
  const token = localStorage.getItem('authToken')
  isAuthenticated.value = !!token
  const cachedUser = localStorage.getItem('user')
  if (cachedUser && !user.value) {
    try { user.value = JSON.parse(cachedUser) } catch (e) { /* ignore */ }
  }
  if (token) {
    try {
      const res = await api.get('/auth/user/')
      user.value = res.data
      localStorage.setItem('user', JSON.stringify(res.data))
    } catch (e) {
      // ignore, interceptor handles 401
    }
  } else {
    user.value = null
    localStorage.removeItem('user')
  }
}

onMounted(syncAuth)

// Re-sync auth whenever route changes (after login redirect) to refresh dropdown state
watch(() => route.fullPath, () => {
  syncAuth()
})
</script>

<style scoped>
.logo-mini {
  height: 28px;
  width: auto;
}
</style>
