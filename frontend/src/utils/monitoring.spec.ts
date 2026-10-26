// SPDX-License-Identifier: GPL-3.0-or-later
import { describe, expect, it } from 'vitest'

import { formatAge, formatPercent } from './monitoring'

describe('formatPercent', () => {
  it('shows one decimal', () => {
    expect(formatPercent(95)).toBe('95.0 %')
  })

  it('shows a dash with nothing measured', () => {
    expect(formatPercent(null)).toBe('–')
  })
})

describe('formatAge', () => {
  it.each([
    [45, '45 s'],
    [720, '12 min'],
    [19800, '5.5 h'],
    [276480, '3.2 d'],
  ])('%d seconds is %s', (seconds, text) => {
    expect(formatAge(seconds)).toBe(text)
  })

  it('shows a dash for no value', () => {
    expect(formatAge(null)).toBe('–')
  })
})
