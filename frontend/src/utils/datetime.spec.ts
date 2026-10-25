// SPDX-License-Identifier: GPL-3.0-or-later
import { afterEach, describe, expect, it } from 'vitest'

import {
  calendarDayLabel,
  filenameTimestamp,
  formatDateTime,
  formatRelativeTime,
  setDisplayLocale,
  setDisplayTimeZone,
} from './datetime'

afterEach(() => {
  setDisplayTimeZone(undefined)
  setDisplayLocale(undefined)
})

describe('display timezone', () => {
  it('formats UTC timestamps in the configured timezone', () => {
    setDisplayLocale('en-GB')
    setDisplayTimeZone('Australia/Sydney')

    // 23:30 UTC on 22 Oct is 10:30 on 23 Oct in Sydney (AEDT, UTC+11).
    expect(formatDateTime('2026-10-22T23:30:00Z')).toBe('23/10/2026, 10:30:00')
  })

  it('ignores an invalid timezone instead of throwing', () => {
    setDisplayTimeZone('Mars/Olympus_Mons')

    expect(formatDateTime('2026-10-22T23:30:00Z')).not.toBe('')
  })

  it('returns an empty string for missing or unparseable values', () => {
    expect(formatDateTime(null)).toBe('')
    expect(formatDateTime('not a date')).toBe('')
  })

  it('builds filename timestamps in the display timezone', () => {
    setDisplayTimeZone('Australia/Sydney')

    expect(filenameTimestamp('2026-10-22T23:30:05Z')).toBe('20261023-103005')
  })
})

describe('formatRelativeTime', () => {
  const now = new Date('2026-10-23T12:00:00Z')

  it.each([
    ['2026-10-23T11:59:40Z', 'Just now'],
    ['2026-10-23T11:15:00Z', '45m ago'],
    ['2026-10-23T07:00:00Z', '5h ago'],
    ['2026-10-20T12:00:00Z', '3d ago'],
  ])('%s -> %s', (value, expected) => {
    expect(formatRelativeTime(value, now)).toBe(expected)
  })
})

describe('calendarDayLabel', () => {
  it('labels the calendar date itself, independent of any timezone', () => {
    setDisplayTimeZone('America/Los_Angeles')

    // new Date('2026-10-22') would be the 21st in Los Angeles.
    expect(calendarDayLabel('2026-10-22')).toEqual({ weekday: 'Thu', day: 22, month: 'Oct' })
  })
})
