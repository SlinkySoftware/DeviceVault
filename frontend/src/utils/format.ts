// SPDX-License-Identifier: GPL-3.0-or-later
import type { PushRejectionReason } from '@/api/types'

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

const PUSH_PROTOCOLS: Record<string, string> = { ssh: 'SCP/SFTP', tftp: 'TFTP' }

/** Display label for a push protocol (`ssh` covers SCP and SFTP). */
export function pushProtocolLabel(protocol: string): string {
  return PUSH_PROTOCOLS[protocol] ?? protocol.toUpperCase()
}

/** A backup's change summary for display: "+3 −1", "No change", "First backup", "Changed", or "" when unknown. */
export function changeLabel(job: {
  changed: boolean | null
  lines_added: number | null
  lines_removed: number | null
  compared_to: string | null
}): string {
  if (job.changed === null) return ''
  if (!job.changed) return 'No change'
  if (job.compared_to === null) return 'First backup'
  if (job.lines_added === null || job.lines_removed === null) return 'Changed'
  return `+${job.lines_added} −${job.lines_removed}`
}

const PUSH_REASONS: Record<PushRejectionReason, string> = {
  unknown_source: 'Unknown source address',
  auth_failed: 'Login failed',
  wrong_protocol: 'Wrong protocol for the device',
  filename: 'File name not accepted',
  too_large: 'File too large',
  device_changed: 'Device changed meanwhile',
  error: 'Could not be stored',
}

/** Why a receiver refused a push, for people. */
export function pushReasonLabel(reason: PushRejectionReason): string {
  return PUSH_REASONS[reason] ?? reason
}
