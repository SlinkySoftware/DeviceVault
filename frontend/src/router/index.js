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

export default createRouter({ 
  history: createWebHistory(), 
  routes: [
    { path: '/', component: Dashboard },
    { path: '/devices', component: Devices },
    { path: '/devices/:id', component: EditDevice },
    { path: '/devices/:id/backups', component: ViewBackups },
    { path: '/admin/device-types', component: DeviceTypes },
    { path: '/admin/manufacturers', component: Manufacturers },
    { path: '/admin/credentials', component: Credentials },
    { path: '/admin/backup-locations', component: BackupLocations },
    { path: '/admin/retention-policies', component: RetentionPolicies }
  ] 
})
