// SPDX-License-Identifier: GPL-3.0-or-later
// Receiver monitoring relays: the URL Zabbix proxies poll, and the snapshots a relay holds.
import type { RelayStatus, Worker } from '@/api/types'

/** `https://<host>:<port>`, bracketing an IPv6 address. */
export function relayUrl(host: string, port: number): string {
  const name = host.includes(':') && !host.startsWith('[') ? `[${host}]` : host
  return `https://${name}:${port}`
}

/** A receiver's relay status, when it reports one with the relay enabled. */
export function enabledRelay(worker: Worker): RelayStatus | null {
  const relay = worker.runtime.receiver?.monitoring
  return relay?.enabled ? relay : null
}

/** The oldest loaded snapshot's publish time (the one most likely to go stale), and whether any is stale. */
export function snapshotSummary(relay: RelayStatus): { count: number; oldest: string | null; stale: boolean } {
  const snapshots = Object.values(relay.snapshots ?? {})
  const oldest = snapshots.map((s) => s.published_at).sort()[0] ?? null
  return { count: snapshots.length, oldest, stale: snapshots.some((s) => s.stale) }
}
