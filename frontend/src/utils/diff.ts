// SPDX-License-Identifier: GPL-3.0-or-later
// Side-by-side line diff for comparing two configuration backups.
//
// Uses Myers' algorithm (the `diff` package), which is roughly linear for
// similar inputs; the previous hand-rolled LCS needed an n x m table and could
// not handle large configurations.

import { diffChars, diffLines } from 'diff'

export type RowKind = 'equal' | 'added' | 'removed' | 'modified'

export interface Segment {
  text: string
  changed: boolean
}

export interface DiffRow {
  kind: RowKind
  /** Line text, or null when the line only exists on the other side. */
  left: string | null
  right: string | null
  leftNumber: number | null
  rightNumber: number | null
  /** Character-level highlights, only for modified rows. */
  leftSegments?: Segment[]
  rightSegments?: Segment[]
}

export interface DiffSummary {
  added: number
  removed: number
  modified: number
}

// Character diffs are quadratic in the worst case; skip them for long lines.
const MAX_INTRALINE_LENGTH = 2000

function splitLines(text: string): string[] {
  const lines = text.split('\n')
  if (lines.length > 1 && lines[lines.length - 1] === '') lines.pop()
  return lines
}

function intraline(left: string, right: string): Pick<DiffRow, 'leftSegments' | 'rightSegments'> {
  if (left.length > MAX_INTRALINE_LENGTH || right.length > MAX_INTRALINE_LENGTH) return {}
  const leftSegments: Segment[] = []
  const rightSegments: Segment[] = []
  for (const change of diffChars(left, right)) {
    if (!change.added) leftSegments.push({ text: change.value, changed: !!change.removed })
    if (!change.removed) rightSegments.push({ text: change.value, changed: !!change.added })
  }
  return { leftSegments, rightSegments }
}

export function sideBySideDiff(left: string, right: string): DiffRow[] {
  const rows: DiffRow[] = []
  let leftNumber = 0
  let rightNumber = 0
  let removed: string[] = []
  let added: string[] = []

  // Pair a run of removals with the following run of additions as "modified".
  const flush = () => {
    const paired = Math.min(removed.length, added.length)
    for (let i = 0; i < Math.max(removed.length, added.length); i++) {
      const l = i < removed.length ? removed[i]! : null
      const r = i < added.length ? added[i]! : null
      rows.push({
        kind: i < paired ? 'modified' : l !== null ? 'removed' : 'added',
        left: l,
        right: r,
        leftNumber: l !== null ? ++leftNumber : null,
        rightNumber: r !== null ? ++rightNumber : null,
        ...(i < paired ? intraline(l!, r!) : {}),
      })
    }
    removed = []
    added = []
  }

  for (const change of diffLines(left, right)) {
    const lines = splitLines(change.value)
    if (change.removed) {
      removed.push(...lines)
    } else if (change.added) {
      added.push(...lines)
    } else {
      flush()
      for (const line of lines) {
        rows.push({ kind: 'equal', left: line, right: line, leftNumber: ++leftNumber, rightNumber: ++rightNumber })
      }
    }
  }
  flush()
  return rows
}

export function summarise(rows: DiffRow[]): DiffSummary {
  const summary: DiffSummary = { added: 0, removed: 0, modified: 0 }
  for (const row of rows) {
    if (row.kind !== 'equal') summary[row.kind]++
  }
  return summary
}
