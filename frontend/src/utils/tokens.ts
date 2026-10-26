// SPDX-License-Identifier: GPL-3.0-or-later

/** Addresses or CIDRs typed one per line (or separated by commas or spaces), without blanks or repeats. */
export function parseNetworks(text: string): string[] {
  const entries = text
    .split(/[\s,]+/)
    .map((entry) => entry.trim())
    .filter(Boolean)
  return [...new Set(entries)]
}
