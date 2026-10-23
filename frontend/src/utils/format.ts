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

const ACTIVE_JOB_STATES: readonly string[] = ['queued', 'collecting', 'collected', 'storing']

/** Whether a backup job (by state) is still in progress. */
export function isActiveJob(state: string | null | undefined): boolean {
  return !!state && ACTIVE_JOB_STATES.includes(state)
}

/** Display label for a backup job state or device backup status. */
export function statusLabel(status: string | null | undefined): string {
  return status === 'timed_out' ? 'Timed out' : capitalise(status)
}

/** Quasar colour for a backup job state or device backup status. */
export function statusColor(status: string | null | undefined): string {
  if (isActiveJob(status)) return 'warning'
  switch (status) {
    case 'stored':
    case 'success':
      return 'positive'
    case 'failed':
    case 'failure':
    case 'timed_out':
      return 'negative'
    default:
      return 'grey'
  }
}

export function statusIcon(status: string | null | undefined): string {
  if (isActiveJob(status)) return 'autorenew'
  switch (status) {
    case 'stored':
    case 'success':
      return 'check_circle'
    case 'failed':
    case 'failure':
      return 'error'
    case 'timed_out':
      return 'timer_off'
    default:
      return 'info'
  }
}

/** Milliseconds as a short duration, e.g. "850 ms", "4.2 s", "3 min 5 s". */
export function formatDuration(ms: number | null | undefined): string {
  if (ms === null || ms === undefined) return ''
  if (ms < 1000) return `${ms} ms`
  const seconds = ms / 1000
  if (seconds < 60) return `${seconds.toFixed(1)} s`
  return `${Math.floor(seconds / 60)} min ${Math.round(seconds % 60)} s`
}
