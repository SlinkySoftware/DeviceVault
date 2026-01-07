/**
 * Vue Router Configuration
 * 
 * Defines all application routes and implements authentication guard
 * to protect routes requiring login.
 * 
 * Route Types:
 * - Public: Login page (requiresAuth: false)
 * - Protected: All other pages (requiresAuth: true)
 */

import { createRouter, createWebHistory } from 'vue-router'
import Dashboard from '../pages/Dashboard.vue'
import Devices from '../pages/Devices.vue'
import EditDevice from '../pages/EditDevice.vue'
import ViewBackups from '../pages/ViewBackups.vue'
import DeviceTypes from '../pages/DeviceTypes.vue'
import Manufacturers from '../pages/Manufacturers.vue'
import Credentials from '../pages/Credentials.vue'
import BackupLocations from '../pages/BackupLocations.vue'
import BackupSchedules from '../pages/BackupSchedules.vue'
import RetentionPolicies from '../pages/RetentionPolicies.vue'
import Profile from '../pages/Profile.vue'
import Users from '../pages/Users.vue'
import Login from '../pages/Login.vue'

/**
 * Application Routes Configuration
 * 
 * Each route includes:
 * - path: URL path (without leading domain)
 * - component: Vue component to render
 * - meta.requiresAuth: Whether login is required (default: true)
 * 
 * Route Groups:
 * - Authentication: /login
 * - Main: / (Dashboard), /devices, /profile
 * - Admin (Vault Admin): /vaultadmin/*
 */
const routes = [
  // ===== Public Routes =====
  { path: '/login', component: Login, meta: { requiresAuth: false } },
  
  // ===== Main Routes (User-facing) =====
  { path: '/', component: Dashboard, meta: { requiresAuth: true } },
  { path: '/devices', component: Devices, meta: { requiresAuth: true } },
  { path: '/devices/:id', component: EditDevice, meta: { requiresAuth: true } },
  { path: '/devices/:id/backups', component: ViewBackups, meta: { requiresAuth: true } },
  { path: '/profile', component: Profile, meta: { requiresAuth: true } },
  
  // ===== Admin Routes (/vaultadmin) =====
  { path: '/vaultadmin/device-types', component: DeviceTypes, meta: { requiresAuth: true } },
  { path: '/vaultadmin/manufacturers', component: Manufacturers, meta: { requiresAuth: true } },
  { path: '/vaultadmin/credentials', component: Credentials, meta: { requiresAuth: true } },
  { path: '/vaultadmin/backup-locations', component: BackupLocations, meta: { requiresAuth: true } },
  { path: '/vaultadmin/backup-schedules', component: BackupSchedules, meta: { requiresAuth: true } },
  { path: '/vaultadmin/retention-policies', component: RetentionPolicies, meta: { requiresAuth: true } },
  { path: '/vaultadmin/users', component: Users, meta: { requiresAuth: true } }
]

/**
 * Create Vue Router instance with history mode
 * 
 * History Mode: Uses browser History API for clean URLs (no #)
 * Routes: Defined above
 */
const router = createRouter({ 
  history: createWebHistory(), 
  routes
})

/**
 * Authentication Guard: Protect routes requiring login
 * 
 * Executes before each route navigation to check:
 * 1. Is route protected? (requiresAuth: true)
 * 2. Is user authenticated? (authToken in localStorage)
 * 3. Redirect to login if needed
 * 
 * Rules:
 * - Protected route + no auth → Redirect to /login
 * - Login page + authenticated → Redirect to /
 * - All others → Allow navigation
 * 
 * Parameters:
 * - to: Destination route
 * - from: Current route
 * - next: Function to proceed or redirect
 */
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
    // Allow navigation
    next()
  }
})

export default router
