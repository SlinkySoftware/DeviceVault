// SPDX-License-Identifier: GPL-3.0-or-later

export interface NavLink {
  label: string
  icon: string
  to: string
  /** Also shown to administrators of a device group (otherwise global administrators only). */
  groupAdmins?: boolean
}

export interface NavSection {
  label: string
  icon: string
  links: NavLink[]
}

export const MAIN_LINKS: NavLink[] = [
  { label: 'Dashboard', icon: 'dashboard', to: '/' },
  { label: 'Devices', icon: 'devices', to: '/devices' },
]

/** Shown when config search is available to the user (auth.searchAvailable). */
export const SEARCH_LINK: NavLink = { label: 'Config Search', icon: 'manage_search', to: '/search' }

export const ADMIN_SECTIONS: NavSection[] = [
  {
    label: 'User Settings',
    icon: 'people',
    links: [
      { label: 'Users', icon: 'person', to: '/vaultadmin/users' },
      { label: 'User Groups', icon: 'group', to: '/vaultadmin/user-groups' },
      { label: 'Service Accounts', icon: 'smart_toy', to: '/vaultadmin/service-accounts' },
      { label: 'Access', icon: 'grid_on', to: '/vaultadmin/access' },
      { label: 'Auth Providers', icon: 'badge', to: '/vaultadmin/auth-providers' },
      { label: 'Audit Log', icon: 'policy', to: '/vaultadmin/audit-log' },
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
      { label: 'Credentials', icon: 'vpn_key', to: '/vaultadmin/credentials', groupAdmins: true },
      { label: 'Storage Targets', icon: 'storage', to: '/vaultadmin/storage-targets' },
      { label: 'Backup Schedules', icon: 'schedule', to: '/vaultadmin/backup-schedules' },
      { label: 'Retention Policies', icon: 'history', to: '/vaultadmin/retention-policies' },
    ],
  },
  {
    label: 'Application Settings',
    icon: 'settings_applications',
    links: [
      { label: 'Collection Groups', icon: 'hub', to: '/vaultadmin/collection-groups' },
      { label: 'Workers', icon: 'memory', to: '/vaultadmin/workers' },
      { label: 'Flower', icon: 'local_florist', to: '/vaultadmin/flower' },
      { label: 'Monitoring', icon: 'monitor_heart', to: '/vaultadmin/monitoring' },
    ],
  },
]

/** The admin sections and links `auth` may use: everything for global administrators. */
export function adminSectionsFor(globalAdmin: boolean, groupAdmin: boolean): NavSection[] {
  return ADMIN_SECTIONS.map((section) => ({
    ...section,
    links: section.links.filter((link) => globalAdmin || (groupAdmin && link.groupAdmins)),
  })).filter((section) => section.links.length > 0)
}
