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

        <q-expansion-item v-if="isAdmin" icon="admin_panel_settings" label="Admin Settings" header-class="text-primary">
          <q-list>
            <!-- User Settings submenu -->
            <q-expansion-item icon="people" label="User Settings" dense dense-toggle class="submenu-level-1">
              <q-list class="submenu-items">
                <q-item clickable to="/vaultadmin/users" class="submenu-item">
                  <q-item-section avatar>
                    <q-icon name="person" size="xs" />
                  </q-item-section>
                  <q-item-section>
                    <q-item-label>Users</q-item-label>
                  </q-item-section>
                </q-item>

                <q-item clickable to="/vaultadmin/groups" class="submenu-item">
                  <q-item-section avatar>
                    <q-icon name="group" size="xs" />
                  </q-item-section>
                  <q-item-section>
                    <q-item-label>Groups</q-item-label>
                  </q-item-section>
                </q-item>
              </q-list>
            </q-expansion-item>

            <!-- Device Settings submenu -->
            <q-expansion-item icon="devices" label="Device Settings" dense dense-toggle class="submenu-level-1">
              <q-list class="submenu-items">
                <q-item clickable to="/vaultadmin/device-types" class="submenu-item">
                  <q-item-section avatar>
                    <q-icon name="category" size="xs" />
                  </q-item-section>
                  <q-item-section>
                    <q-item-label>Device Types</q-item-label>
                  </q-item-section>
                </q-item>

                <q-item clickable to="/vaultadmin/manufacturers" class="submenu-item">
                  <q-item-section avatar>
                    <q-icon name="business" size="xs" />
                  </q-item-section>
                  <q-item-section>
                    <q-item-label>Manufacturers</q-item-label>
                  </q-item-section>
                </q-item>

                <q-item clickable to="/vaultadmin/device-groups" class="submenu-item">
                  <q-item-section avatar>
                    <q-icon name="workspaces" size="xs" />
                  </q-item-section>
                  <q-item-section>
                    <q-item-label>Device Groups</q-item-label>
                  </q-item-section>
                </q-item>
              </q-list>
            </q-expansion-item>

            <!-- Backup Settings submenu -->
            <q-expansion-item icon="backup" label="Backup Settings" dense dense-toggle class="submenu-level-1">
              <q-list class="submenu-items">
                <q-item clickable to="/vaultadmin/credentials" class="submenu-item">
                  <q-item-section avatar>
                    <q-icon name="vpn_key" size="xs" />
                  </q-item-section>
                  <q-item-section>
                    <q-item-label>Credentials</q-item-label>
                  </q-item-section>
                </q-item>

                <q-item clickable to="/vaultadmin/backup-locations" class="submenu-item">
                  <q-item-section avatar>
                    <q-icon name="folder" size="xs" />
                  </q-item-section>
                  <q-item-section>
                    <q-item-label>Backup Locations</q-item-label>
                  </q-item-section>
                </q-item>

                <q-item clickable to="/vaultadmin/backup-schedules" class="submenu-item">
                  <q-item-section avatar>
                    <q-icon name="schedule" size="xs" />
                  </q-item-section>
                  <q-item-section>
                    <q-item-label>Backup Schedules</q-item-label>
                  </q-item-section>
                </q-item>

                <q-item clickable to="/vaultadmin/retention-policies" class="submenu-item">
                  <q-item-section avatar>
                    <q-icon name="history" size="xs" />
                  </q-item-section>
                  <q-item-section>
                    <q-item-label>Retention Policies</q-item-label>
                  </q-item-section>
                </q-item>
              </q-list>
            </q-expansion-item>
          </q-list>
        </q-expansion-item>
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

// Consider both staff and superuser as admin for UI visibility
const isAdmin = computed(() => !!(user.value && (user.value.is_staff || user.value.is_superuser)))
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
      // Persist flags for other components that might rely on them
      const isAdminFlag = !!(res.data.is_staff || res.data.is_superuser)
      localStorage.setItem('isAdmin', String(isAdminFlag))
      localStorage.setItem('ignoreTags', String(!!res.data.ignore_tags))
      
      // Fetch and apply user theme preference
      try {
        const prefs = await api.get('/user/preferences/')
        const theme = prefs.data.theme || 'dark'
        localStorage.setItem('userTheme', theme)
        $q.dark.set(theme === 'dark')
      } catch (e) {
        // Default to dark mode if preference fetch fails
        $q.dark.set(true)
      }
    } catch (e) {
      // ignore, interceptor handles 401
    }
  } else {
    user.value = null
    localStorage.removeItem('user')
    localStorage.removeItem('isAdmin')
    localStorage.removeItem('ignoreTags')
  }
}

onMounted(() => {
  // Initialize theme from localStorage or default to dark
  const savedTheme = localStorage.getItem('userTheme') || 'dark'
  $q.dark.set(savedTheme === 'dark')
  syncAuth()
})

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

/* Tree view indentation for nested submenus */
.submenu-level-1 {
  padding-left: 8px;
}

.submenu-items {
  background-color: rgba(0, 0, 0, 0.05);
}

.submenu-item {
  padding-left: 32px;
  min-height: 40px;
}

/* Dark mode adjustments */
body.body--dark .submenu-items {
  background-color: rgba(255, 255, 255, 0.03);
}
</style>
