// SPDX-License-Identifier: GPL-3.0-or-later
import { describe, expect, it } from 'vitest'

import type { RelayStatus, Worker } from '@/api/types'

import { enabledRelay, relayUrl, snapshotSummary } from './relay'

function relay(overrides: Partial<RelayStatus> = {}): RelayStatus {
  return {
    enabled: true,
    port: 8443,
    listening: true,
    error: '',
    certificate_fingerprint: 'AB:CD',
    tokens: 1,
    snapshots: {},
    requests: 0,
    refused: 0,
    throttled: 0,
    ...overrides,
  }
}

function worker(monitoring?: RelayStatus): Worker {
  return {
    runtime: { receiver: { host_key_fingerprint: '', vault_kid: null, devices: 0, listeners: {}, monitoring } },
  } as unknown as Worker
}

describe('relayUrl', () => {
  it('builds an https URL', () => {
    expect(relayUrl('receiver-a', 8443)).toBe('https://receiver-a:8443')
  })

  it('brackets IPv6 addresses', () => {
    expect(relayUrl('2001:db8::1', 9443)).toBe('https://[2001:db8::1]:9443')
    expect(relayUrl('[2001:db8::1]', 9443)).toBe('https://[2001:db8::1]:9443')
  })
})

describe('enabledRelay', () => {
  it('is the status only while the relay is enabled', () => {
    expect(enabledRelay(worker(relay()))?.port).toBe(8443)
    expect(enabledRelay(worker(relay({ enabled: false })))).toBeNull()
    expect(enabledRelay(worker())).toBeNull()
  })
})

describe('snapshotSummary', () => {
  it('finds the oldest snapshot and any stale one', () => {
    const summary = snapshotSummary(
      relay({
        snapshots: {
          '5': { generation: 'a', published_at: '2026-10-01T12:15:00+00:00', devices: 3, stale: false },
          '6': { generation: 'b', published_at: '2026-10-01T12:00:00+00:00', devices: 1, stale: true },
        },
      }),
    )
    expect(summary).toEqual({ count: 2, oldest: '2026-10-01T12:00:00+00:00', stale: true })
  })

  it('is empty without snapshots', () => {
    expect(snapshotSummary(relay())).toEqual({ count: 0, oldest: null, stale: false })
  })
})
