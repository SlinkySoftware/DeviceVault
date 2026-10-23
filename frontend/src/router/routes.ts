// SPDX-License-Identifier: GPL-3.0-or-later
import type { RouteRecordRaw } from 'vue-router'

declare module 'vue-router' {
  interface RouteMeta {
    /** Reachable without signing in. */
    public?: boolean
    requiresAdmin?: boolean
    requiresSuperuser?: boolean
    title?: string
  }
}

const admin = (path: string, name: string, title: string, component: RouteRecordRaw['component']) =>
  ({ path: `vaultadmin/${path}`, name, component, meta: { requiresAdmin: true, title } }) as RouteRecordRaw

const routes: RouteRecordRaw[] = [
  {
    path: '/login',
    component: () => import('@/layouts/BlankLayout.vue'),
    meta: { public: true },
    children: [{ path: '', name: 'login', component: () => import('@/pages/LoginPage.vue'), meta: { public: true } }],
  },
  {
    path: '/',
    component: () => import('@/layouts/MainLayout.vue'),
    children: [
      { path: '', name: 'dashboard', component: () => import('@/pages/DashboardPage.vue'), meta: { title: 'Dashboard' } },
      { path: 'devices', name: 'devices', component: () => import('@/pages/DevicesPage.vue'), meta: { title: 'Devices' } },
      {
        path: 'devices/new',
        name: 'device-new',
        component: () => import('@/pages/EditDevicePage.vue'),
        meta: { title: 'Add Device' },
      },
      {
        path: 'devices/:id(\\d+)',
        name: 'device-edit',
        component: () => import('@/pages/EditDevicePage.vue'),
        meta: { title: 'Configure Device' },
      },
      {
        path: 'devices/:id(\\d+)/backups',
        name: 'device-backups',
        component: () => import('@/pages/ViewBackupsPage.vue'),
        meta: { title: 'Backups' },
      },
      {
        path: 'devices/:id(\\d+)/backups/compare',
        name: 'device-backups-compare',
        component: () => import('@/pages/CompareBackupsPage.vue'),
        meta: { title: 'Compare Backups' },
      },
      { path: 'profile', name: 'profile', component: () => import('@/pages/ProfilePage.vue'), meta: { title: 'Profile' } },

      admin('users', 'users', 'Users', () => import('@/pages/admin/UsersPage.vue')),
      admin('groups', 'groups', 'Groups', () => import('@/pages/admin/GroupsPage.vue')),
      admin('device-types', 'device-types', 'Device Types', () => import('@/pages/admin/DeviceTypesPage.vue')),
      admin('manufacturers', 'manufacturers', 'Manufacturers', () => import('@/pages/admin/ManufacturersPage.vue')),
      admin('backup-methods', 'backup-methods', 'Backup Methods', () => import('@/pages/admin/BackupMethodsPage.vue')),
      admin('device-groups', 'device-groups', 'Device Groups', () => import('@/pages/admin/DeviceGroupsPage.vue')),
      admin('credentials', 'credentials', 'Credentials', () => import('@/pages/admin/CredentialsPage.vue')),
      admin('storage-targets', 'storage-targets', 'Storage Targets', () =>
        import('@/pages/admin/StorageTargetsPage.vue'),
      ),
      admin('backup-schedules', 'backup-schedules', 'Backup Schedules', () =>
        import('@/pages/admin/BackupSchedulesPage.vue'),
      ),
      admin('retention-policies', 'retention-policies', 'Retention Policies', () =>
        import('@/pages/admin/RetentionPoliciesPage.vue'),
      ),
      {
        path: 'vaultadmin/collection-groups',
        name: 'collection-groups',
        component: () => import('@/pages/admin/CollectionGroupsPage.vue'),
        meta: { requiresSuperuser: true, title: 'Collection Groups' },
      },
      {
        path: 'vaultadmin/workers',
        name: 'workers',
        component: () => import('@/pages/admin/WorkersPage.vue'),
        meta: { requiresSuperuser: true, title: 'Workers' },
      },
      {
        path: 'vaultadmin/flower',
        name: 'flower',
        component: () => import('@/pages/admin/FlowerPage.vue'),
        meta: { requiresSuperuser: true, title: 'Flower' },
      },
    ],
  },
  { path: '/:catchAll(.*)*', redirect: { name: 'dashboard' } },
]

export default routes
