// SPDX-License-Identifier: GPL-3.0-or-later
import { describe, expect, it } from 'vitest'

import { emptyFlags, flagLetters, heldFlags, lockedFlags, setFlag } from './grants'

describe('grant flags', () => {
  it('turns on what a flag needs', () => {
    expect(heldFlags(setFlag(emptyFlags(), 'download', true))).toEqual(['view', 'view_contents', 'download'])
    expect(heldFlags(setFlag(emptyFlags(), 'admin', true))).toEqual([
      'view',
      'backup_now',
      'view_contents',
      'download',
      'admin',
    ])
  })

  it('turns off what needs a flag', () => {
    const all = setFlag(emptyFlags(), 'admin', true)
    expect(heldFlags(setFlag(all, 'view_contents', false))).toEqual(['view', 'backup_now'])
  })

  it('locks the flags that ticked ones need', () => {
    expect([...lockedFlags(setFlag(emptyFlags(), 'download', true))].sort()).toEqual(['view', 'view_contents'])
    expect(lockedFlags(emptyFlags()).size).toBe(0)
  })

  it('summarises flags as letters in order', () => {
    expect(flagLetters(['download', 'view', 'view_contents'])).toBe('S C D')
  })
})
