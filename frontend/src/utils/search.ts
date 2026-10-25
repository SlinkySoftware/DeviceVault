// SPDX-License-Identifier: GPL-3.0-or-later
// Config search results: secret values are indexed as `{{secret:<hex>}}` tokens.
import type { SearchMode } from '@/api/types'

export interface LineSegment {
  text: string
  /** A secret token: shown as a chip rather than as text. */
  secret: boolean
  /** Part of what the search matched. */
  match?: boolean
}

const TOKEN = /\{\{secret:[0-9a-f]{32}\}\}/g

/** A result line split into plain text and secret tokens. */
export function splitSecretTokens(line: string): LineSegment[] {
  const segments: LineSegment[] = []
  let last = 0
  for (const match of line.matchAll(TOKEN)) {
    if (match.index > last) segments.push({ text: line.slice(last, match.index), secret: false })
    segments.push({ text: match[0], secret: true })
    last = match.index + match[0].length
  }
  if (last < line.length || segments.length === 0) segments.push({ text: line.slice(last), secret: false })
  return segments
}

function escapeRegex(value: string): string {
  return value.replace(/[.*+?^${}()|[\]\\]/g, '\\$&')
}

/** The search as a JavaScript regex, or null when it cannot be highlighted. The server matches text and
 * RE2 patterns case-insensitively; a pattern JavaScript rejects, and a secret search (whose value is never
 * sent back), show no highlights. */
export function highlightPattern(mode: SearchMode, query: string): RegExp | null {
  if (!query || mode === 'secret') return null
  try {
    return new RegExp(mode === 'regex' ? query : escapeRegex(query), 'gi')
  } catch {
    return null
  }
}

/** Where ``pattern`` matches ``line``, as [start, end) ranges. */
function matchRanges(line: string, pattern: RegExp): [number, number][] {
  const ranges: [number, number][] = []
  for (const match of line.matchAll(pattern)) {
    if (match[0].length) ranges.push([match.index, match.index + match[0].length])
  }
  return ranges
}

/** A result line split into secret tokens and text, with the parts ``pattern`` matches marked. */
export function highlightLine(line: string, pattern: RegExp | null): LineSegment[] {
  const segments = splitSecretTokens(line)
  const ranges = pattern ? matchRanges(line, pattern) : []
  if (!ranges.length) return segments
  const highlighted: LineSegment[] = []
  let offset = 0
  for (const segment of segments) {
    const start = offset
    const end = offset + segment.text.length
    offset = end
    if (segment.secret) {
      highlighted.push({ ...segment, match: ranges.some(([from, to]) => from < end && to > start) })
      continue
    }
    let cursor = start
    for (const [from, to] of ranges) {
      if (to <= cursor || from >= end) continue
      if (from > cursor) highlighted.push({ text: line.slice(cursor, from), secret: false })
      const stop = Math.min(to, end)
      highlighted.push({ text: line.slice(Math.max(from, cursor), stop), secret: false, match: true })
      cursor = stop
    }
    if (cursor < end) highlighted.push({ text: line.slice(cursor, end), secret: false })
  }
  return highlighted
}
