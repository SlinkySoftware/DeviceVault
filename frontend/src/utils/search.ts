// SPDX-License-Identifier: GPL-3.0-or-later
// Config search results: secret values are indexed as `{{secret:<hex>}}` tokens.

export interface LineSegment {
  text: string
  /** A secret token: shown as a chip rather than as text. */
  secret: boolean
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
