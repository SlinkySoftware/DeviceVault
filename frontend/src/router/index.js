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
    { path: '/vaultadmin/device-types', component: DeviceTypes },
    { path: '/vaultadmin/manufacturers', component: Manufacturers },
    { path: '/vaultadmin/credentials', component: Credentials },
    { path: '/vaultadmin/backup-locations', component: BackupLocations },
    { path: '/vaultadmin/retention-policies', component: RetentionPolicies }
  ] 
})
