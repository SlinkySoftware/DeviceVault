// SPDX-License-Identifier: GPL-3.0-or-later
import { describe, expect, it } from 'vitest'

import { formatDuration, isActiveJob, statusColor, statusLabel } from './format'

describe('job states', () => {
  it('treats only unfinished states as active', () => {
    expect(['queued', 'collecting', 'collected', 'storing'].every(isActiveJob)).toBe(true)
    expect(['stored', 'failed', 'timed_out', '', null].some(isActiveJob)).toBe(false)
  })

  it('colours outcomes', () => {
    expect(statusColor('stored')).toBe('positive')
    expect(statusColor('timed_out')).toBe('negative')
    expect(statusColor('storing')).toBe('warning')
    expect(statusLabel('timed_out')).toBe('Timed out')
  })
})

describe('formatDuration', () => {
  it.each([
    [null, ''],
    [850, '850 ms'],
    [4200, '4.2 s'],
    [185_000, '3 min 5 s'],
  ])('%s -> %s', (ms, expected) => {
    expect(formatDuration(ms)).toBe(expected)
  })
})
