// SPDX-License-Identifier: GPL-3.0-or-later
import { describe, expect, it } from 'vitest'

import { compactNumber, labelEvery, niceTicks } from './scale'

describe('niceTicks', () => {
  it('rounds the step and covers the maximum', () => {
    expect(niceTicks(7)).toEqual([0, 2, 4, 6, 8])
    expect(niceTicks(100)).toEqual([0, 25, 50, 75, 100])
    expect(niceTicks(0.3)).toEqual([0, 0.1, 0.2, 0.3])
    expect(niceTicks(1234)).toEqual([0, 500, 1000, 1500])
    expect(niceTicks(1, 4, false, true)).toEqual([0, 1])
    expect(niceTicks(3, 4, false, true)).toEqual([0, 1, 2, 3])
  })

  it('keeps a fixed maximum', () => {
    expect(niceTicks(100, 4, true)).toEqual([0, 25, 50, 75, 100])
  })

  it('draws an axis without data', () => {
    expect(niceTicks(0)).toEqual([0, 1])
  })
})

describe('labelEvery', () => {
  it('thins labels that would not fit', () => {
    expect(labelEvery(7, 700, 48)).toBe(1)
    expect(labelEvery(90, 600, 48)).toBe(8)
    expect(labelEvery(0, 600, 48)).toBe(1)
  })
})

describe('compactNumber', () => {
  it('shortens large numbers', () => {
    expect(compactNumber(950)).toBe('950')
    expect(compactNumber(2.25)).toBe('2.3')
    expect(compactNumber(1200)).toBe('1.2K')
  })
})
