// SPDX-License-Identifier: GPL-3.0-or-later
import { describe, expect, it } from 'vitest'

import { holdLabel, inactiveSummary, type LifecycleDevice, nextStep } from './lifecycle'

const active: LifecycleDevice = {
  lifecycle: 'active',
  held_until: null,
  held_backups: 3,
  pinned_backups: 0,
  purge_requested_at: null,
  can_delete: false,
  inactive_at: null,
  inactive_by_username: null,
  inactive_reason: '',
}

const inactive = (fields: Partial<LifecycleDevice> = {}): LifecycleDevice => ({
  ...active,
  lifecycle: 'inactive',
  inactive_at: '2026-10-01T00:00:00Z',
  ...fields,
})

const deletable = inactive({ lifecycle: 'deletable', held_backups: 0, can_delete: true })

describe('holdLabel', () => {
  it.each([
    [active, null],
    [deletable, 'Ready to delete'],
    [inactive({ purge_requested_at: '2026-10-02T00:00:00Z', pinned_backups: 1 }), 'Purging (3 left)'],
    [inactive({ pinned_backups: 1 }), 'Held by 1 pinned backup'],
    [inactive({ pinned_backups: 2 }), 'Held by 2 pinned backups'],
    [inactive(), 'Kept (no policy limit)'],
  ])('%#', (device, expected) => {
    expect(holdLabel(device)).toBe(expected)
  })

  it('names the end of the hold', () => {
    expect(holdLabel(inactive({ held_until: '2026-12-30T00:00:00Z' }))).toMatch(/^Held until .*2026/)
  })
})

describe('nextStep', () => {
  it('marks active devices inactive, and reactivates inactive ones', () => {
    expect(nextStep(active)).toBe('deactivate')
    expect(nextStep(inactive())).toBe('reactivate')
  })

  it('offers delete once the device can go, active or not', () => {
    expect(nextStep({ ...active, held_backups: 0, can_delete: true })).toBe('delete')
    expect(nextStep(deletable)).toBe('delete')
  })
})

describe('inactiveSummary', () => {
  it('says who and why', () => {
    const summary = inactiveSummary(inactive({ inactive_by_username: 'op', inactive_reason: 'replaced' }))
    expect(summary).toMatch(/^Marked inactive .* by op: replaced$/)
    expect(inactiveSummary(active)).toBe('')
  })
})
