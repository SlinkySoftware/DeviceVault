// SPDX-License-Identifier: GPL-3.0-or-later

export interface NavLink {
  label: string
  icon: string
  to: string
}

export interface NavSection {
  label: string
  icon: string
  links: NavLink[]
  superuserOnly?: boolean
}

export const MAIN_LINKS: NavLink[] = [
  { label: 'Dashboard', icon: 'dashboard', to: '/' },
  { label: 'Devices', icon: 'devices', to: '/devices' },
]

export const ADMIN_SECTIONS: NavSection[] = [
  {
    label: 'User Settings',
    icon: 'people',
    links: [
      { label: 'Users', icon: 'person', to: '/vaultadmin/users' },
      { label: 'Groups', icon: 'group', to: '/vaultadmin/groups' },
    ],
  },
  {
    label: 'Device Settings',
    icon: 'devices',
    links: [
      { label: 'Device Types', icon: 'category', to: '/vaultadmin/device-types' },
      { label: 'Manufacturers', icon: 'factory', to: '/vaultadmin/manufacturers' },
      { label: 'Backup Methods', icon: 'extension', to: '/vaultadmin/backup-methods' },
      { label: 'Device Groups', icon: 'workspaces', to: '/vaultadmin/device-groups' },
    ],
  },
  {
    label: 'Backup Settings',
    icon: 'backup',
    links: [
      { label: 'Credentials', icon: 'vpn_key', to: '/vaultadmin/credentials' },
      { label: 'Storage Targets', icon: 'storage', to: '/vaultadmin/storage-targets' },
      { label: 'Backup Schedules', icon: 'schedule', to: '/vaultadmin/backup-schedules' },
      { label: 'Retention Policies', icon: 'history', to: '/vaultadmin/retention-policies' },
    ],
  },
  {
    label: 'Application Settings',
    icon: 'settings_applications',
    superuserOnly: true,
    links: [
      { label: 'Collection Groups', icon: 'hub', to: '/vaultadmin/collection-groups' },
      { label: 'Workers', icon: 'memory', to: '/vaultadmin/workers' },
      { label: 'Flower', icon: 'local_florist', to: '/vaultadmin/flower' },
    ],
  },
]
