// SPDX-License-Identifier: GPL-3.0-or-later

export function formatBytes(bytes: number | null | undefined): string {
  if (bytes === null || bytes === undefined) return ''
  if (bytes < 1024) return `${bytes} B`
  const units = ['KB', 'MB', 'GB', 'TB']
  let value = bytes / 1024
  let unit = 0
  while (value >= 1024 && unit < units.length - 1) {
    value /= 1024
    unit++
  }
  return `${value.toFixed(1)} ${units[unit]}`
}

export function capitalise(value: string | null | undefined): string {
  if (!value) return ''
  return value.charAt(0).toUpperCase() + value.slice(1)
}

/** Quasar colour for a backup/storage status. */
export function statusColor(status: string | null | undefined): string {
  switch (status) {
    case 'success':
      return 'positive'
    case 'failure':
    case 'failed':
      return 'negative'
    case 'pending':
    case 'in_progress':
      return 'warning'
    default:
      return 'grey'
  }
}

export function statusIcon(status: string | null | undefined): string {
  switch (status) {
    case 'success':
      return 'check_circle'
    case 'failure':
    case 'failed':
      return 'error'
    case 'pending':
    case 'in_progress':
      return 'autorenew'
    case 'n/a':
      return 'remove'
    default:
      return 'info'
  }
}
