// SPDX-License-Identifier: GPL-3.0-or-later
// Timestamps arrive from the API as UTC ISO strings and are shown in the
// orchestrator's configured display timezone (DV_TIMEZONE), so every user sees
// the same wall-clock times the server uses for "last 24h" and daily buckets.
// The timezone is reactive: it loads after the first render, and anything
// formatted before then re-renders when it arrives.

import { shallowRef } from 'vue'

const timeZoneRef = shallowRef<string | undefined>()
let displayLocale: string | undefined

/** Set the IANA timezone used for display; undefined falls back to the browser's. */
export function setDisplayTimeZone(timeZone: string | undefined): void {
  timeZoneRef.value = timeZone && isValidTimeZone(timeZone) ? timeZone : undefined
}

/** Override the display locale (mainly for tests); undefined uses the browser's. */
export function setDisplayLocale(locale: string | undefined): void {
  displayLocale = locale
}

export function isValidTimeZone(timeZone: string): boolean {
  try {
    new Intl.DateTimeFormat('en-US', { timeZone })
    return true
  } catch {
    return false
  }
}

function toDate(value: string | null | undefined): Date | null {
  if (!value) return null
  const date = new Date(value)
  return Number.isNaN(date.getTime()) ? null : date
}

function format(value: string | null | undefined, options: Intl.DateTimeFormatOptions): string {
  const date = toDate(value)
  if (!date) return ''
  return new Intl.DateTimeFormat(displayLocale, { timeZone: timeZoneRef.value, ...options }).format(date)
}

export function formatDateTime(value: string | null | undefined): string {
  return format(value, {
    year: 'numeric',
    month: '2-digit',
    day: '2-digit',
    hour: '2-digit',
    minute: '2-digit',
    second: '2-digit',
    hourCycle: 'h23',
  })
}

export function formatDateTimeShort(value: string | null | undefined): string {
  return format(value, {
    year: 'numeric',
    month: '2-digit',
    day: '2-digit',
    hour: '2-digit',
    minute: '2-digit',
    hourCycle: 'h23',
  })
}

export function formatDate(value: string | null | undefined): string {
  return format(value, { year: 'numeric', month: '2-digit', day: '2-digit' })
}

export function formatRelativeTime(value: string | null | undefined, now: Date = new Date()): string {
  const date = toDate(value)
  if (!date) return ''
  const minutes = Math.floor((now.getTime() - date.getTime()) / 60_000)
  if (minutes < 1) return 'Just now'
  if (minutes < 60) return `${minutes}m ago`
  const hours = Math.floor(minutes / 60)
  if (hours < 24) return `${hours}h ago`
  const days = Math.floor(hours / 24)
  if (days < 7) return `${days}d ago`
  return formatDate(value)
}

/** `YYYYMMDD-HHMMSS` in the display timezone, for download filenames. */
export function filenameTimestamp(value: string): string {
  const date = toDate(value)
  if (!date) return 'unknown'
  const parts = Object.fromEntries(
    new Intl.DateTimeFormat('en-US', {
      timeZone: timeZoneRef.value,
      year: 'numeric',
      month: '2-digit',
      day: '2-digit',
      hour: '2-digit',
      minute: '2-digit',
      second: '2-digit',
      hourCycle: 'h23',
    })
      .formatToParts(date)
      .map((part) => [part.type, part.value]),
  )
  return `${parts.year}${parts.month}${parts.day}-${parts.hour}${parts.minute}${parts.second}`
}

/**
 * Label a calendar day given as `YYYY-MM-DD`. The string is a date, not an
 * instant, so it must not be shifted by any timezone (`new Date('2026-10-22')`
 * is UTC midnight and shows as the 21st west of UTC).
 */
export function calendarDayLabel(isoDate: string): { weekday: string; day: number; month: string } {
  const [year, month, day] = isoDate.split('-').map(Number)
  const date = new Date(Date.UTC(year ?? 1970, (month ?? 1) - 1, day ?? 1))
  return {
    weekday: new Intl.DateTimeFormat(displayLocale ?? 'en-US', { weekday: 'short', timeZone: 'UTC' }).format(date),
    day: date.getUTCDate(),
    month: new Intl.DateTimeFormat(displayLocale ?? 'en-US', { month: 'short', timeZone: 'UTC' }).format(date),
  }
}
