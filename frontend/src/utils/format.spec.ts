// SPDX-License-Identifier: GPL-3.0-or-later
import { describe, expect, it } from 'vitest'

import { changeLabel, formatDuration, isActiveJob, pushProtocolLabel, statusColor, statusLabel } from './format'

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

describe('push protocols', () => {
  it('names SSH uploads by what devices know them as', () => {
    expect(pushProtocolLabel('ssh')).toBe('SCP/SFTP')
    expect(pushProtocolLabel('tftp')).toBe('TFTP')
    expect(pushProtocolLabel('ftp')).toBe('FTP')
  })
})

describe('changeLabel', () => {
  const job = { changed: true, lines_added: 3, lines_removed: 1, compared_to: 'prev' }

  it('summarises a change against the previous backup', () => {
    expect(changeLabel(job)).toBe('+3 −1')
    expect(changeLabel({ ...job, changed: false, lines_added: 0, lines_removed: 0 })).toBe('No change')
  })

  it('names first and binary backups, and is empty until summarised', () => {
    expect(changeLabel({ ...job, compared_to: null })).toBe('First backup')
    expect(changeLabel({ ...job, lines_added: null, lines_removed: null })).toBe('Changed')
    expect(changeLabel({ ...job, changed: null })).toBe('')
  })
})
