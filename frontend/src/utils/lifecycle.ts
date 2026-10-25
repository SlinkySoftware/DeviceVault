// SPDX-License-Identifier: GPL-3.0-or-later
// Where a retired device stands (ARCHITECTURE.md 7.5): what its badge says, and which action it offers.
import type { Device, DeviceDetail } from '@/api/types'
import { formatDate } from '@/utils/datetime'

export type LifecycleDevice = Pick<
  Device | DeviceDetail,
  | 'lifecycle'
  | 'held_until'
  | 'held_backups'
  | 'pinned_backups'
  | 'purge_requested_at'
  | 'can_delete'
  | 'inactive_at'
  | 'inactive_by_username'
  | 'inactive_reason'
>

/** The badge an inactive device shows, or null for an active one. */
export function holdLabel(device: LifecycleDevice): string | null {
  if (device.lifecycle === 'active') return null
  if (device.lifecycle === 'deletable') return 'Ready to delete'
  if (device.purge_requested_at) return `Purging (${device.held_backups} left)`
  if (device.pinned_backups) return `Held by ${device.pinned_backups} pinned backup${device.pinned_backups > 1 ? 's' : ''}`
  if (device.held_until) return `Held until ${formatDate(device.held_until)}`
  return 'Kept (no policy limit)'
}

/** Who retired the device, when and why, for a tooltip. */
export function inactiveSummary(device: LifecycleDevice): string {
  if (!device.inactive_at) return ''
  const who = device.inactive_by_username ? ` by ${device.inactive_by_username}` : ''
  const why = device.inactive_reason ? `: ${device.inactive_reason}` : ''
  return `Marked inactive ${formatDate(device.inactive_at)}${who}${why}`
}

/** The one retirement step a group administrator can take next. */
export function nextStep(device: LifecycleDevice): 'deactivate' | 'delete' | 'reactivate' {
  if (device.can_delete) return 'delete'
  return device.lifecycle === 'active' ? 'deactivate' : 'reactivate'
}
