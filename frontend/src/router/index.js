import { createRouter, createWebHistory } from 'vue-router'
import Dashboard from '../pages/Dashboard.vue'
import Devices from '../pages/Devices.vue'
import EditDevice from '../pages/EditDevice.vue'
import ViewBackups from '../pages/ViewBackups.vue'
import DeviceTypes from '../pages/DeviceTypes.vue'
import Manufacturers from '../pages/Manufacturers.vue'
import Credentials from '../pages/Credentials.vue'
import BackupLocations from '../pages/BackupLocations.vue'
import RetentionPolicies from '../pages/RetentionPolicies.vue'
import Profile from '../pages/Profile.vue'
import Users from '../pages/Users.vue'
import Login from '../pages/Login.vue'

const routes = [
  { path: '/login', component: Login, meta: { requiresAuth: false } },
  { path: '/', component: Dashboard, meta: { requiresAuth: true } },
  { path: '/devices', component: Devices, meta: { requiresAuth: true } },
  { path: '/devices/:id', component: EditDevice, meta: { requiresAuth: true } },
  { path: '/devices/:id/backups', component: ViewBackups, meta: { requiresAuth: true } },
  { path: '/vaultadmin/device-types', component: DeviceTypes, meta: { requiresAuth: true } },
  { path: '/vaultadmin/manufacturers', component: Manufacturers, meta: { requiresAuth: true } },
  { path: '/vaultadmin/credentials', component: Credentials, meta: { requiresAuth: true } },
  { path: '/vaultadmin/backup-locations', component: BackupLocations, meta: { requiresAuth: true } },
  { path: '/vaultadmin/retention-policies', component: RetentionPolicies, meta: { requiresAuth: true } },
  { path: '/profile', component: Profile, meta: { requiresAuth: true } },
  { path: '/vaultadmin/users', component: Users, meta: { requiresAuth: true } }
]

const router = createRouter({ 
  history: createWebHistory(), 
  routes
})

// Authentication guard
router.beforeEach((to, from, next) => {
  const isAuthenticated = !!localStorage.getItem('authToken')
  const requiresAuth = to.meta.requiresAuth !== false

  if (requiresAuth && !isAuthenticated) {
    // Redirect to login if route requires auth and user is not authenticated
    next('/login')
  } else if (to.path === '/login' && isAuthenticated) {
    // Redirect to dashboard if trying to access login while already authenticated
    next('/')
  } else {
    next()
  }
})

export default router
