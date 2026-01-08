/*
* DeviceVault - A comprehensive network device backup management application with web interface for user and admin access and backend component for automated backup collection.
* Copyright (C) 2026, Slinky Software
*
* This program is free software: you can redistribute it and/or modify
* it under the terms of the GNU General Public License as published by
* the Free Software Foundation, either version 3 of the License, or
* (at your option) any later version.
*
* This program is distributed in the hope that it will be useful,
* but WITHOUT ANY WARRANTY; without even the implied warranty of
* MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
* GNU General Public License for more details.
*
* You should have received a copy of the GNU General Public License
* along with this program.  If not, see <http://www.gnu.org/licenses/>.
*/

import { createRouter, createWebHistory } from 'vue-router'
import Dashboard from '../pages/Dashboard.vue'
import Devices from '../pages/Devices.vue'
import EditDevice from '../pages/EditDevice.vue'
import ViewBackups from '../pages/ViewBackups.vue'
import DeviceTypes from '../pages/DeviceTypes.vue'
import BackupMethods from '../pages/BackupMethods.vue'
import Credentials from '../pages/Credentials.vue'
import BackupLocations from '../pages/BackupLocations.vue'
import BackupSchedules from '../pages/BackupSchedules.vue'
import RetentionPolicies from '../pages/RetentionPolicies.vue'
import CollectionGroups from '../pages/CollectionGroups.vue'
import Groups from '../pages/Groups.vue'
import DeviceGroups from '../pages/DeviceGroups.vue'
import Profile from '../pages/Profile.vue'
import Users from '../pages/Users.vue'
import Login from '../pages/Login.vue'
import Theme from '../pages/Theme.vue'

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
  { path: '/vaultadmin/backup-methods', component: BackupMethods, meta: { requiresAuth: true } },
  { path: '/vaultadmin/credentials', component: Credentials, meta: { requiresAuth: true } },
  { path: '/vaultadmin/backup-locations', component: BackupLocations, meta: { requiresAuth: true } },
  { path: '/vaultadmin/backup-schedules', component: BackupSchedules, meta: { requiresAuth: true } },
  { path: '/vaultadmin/retention-policies', component: RetentionPolicies, meta: { requiresAuth: true } },
  { path: '/vaultadmin/collection-groups', component: CollectionGroups, meta: { requiresAuth: true } },
  { path: '/vaultadmin/groups', component: Groups, meta: { requiresAuth: true } },
  { path: '/vaultadmin/device-groups', component: DeviceGroups, meta: { requiresAuth: true } },
  { path: '/vaultadmin/users', component: Users, meta: { requiresAuth: true } },
  { path: '/vaultadmin/theme', component: Theme, meta: { requiresAuth: true } }
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
