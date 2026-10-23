// SPDX-License-Identifier: GPL-3.0-or-later
import { describe, expect, it } from 'vitest'

import { sideBySideDiff, summarise } from './diff'

describe('sideBySideDiff', () => {
  it('marks identical input as equal rows with line numbers on both sides', () => {
    const rows = sideBySideDiff('a\nb\n', 'a\nb\n')

    expect(rows.map((r) => r.kind)).toEqual(['equal', 'equal'])
    expect(rows.map((r) => [r.leftNumber, r.rightNumber])).toEqual([
      [1, 1],
      [2, 2],
    ])
  })

  it('pairs a removal followed by an addition as a modification with character highlights', () => {
    const [, modified] = sideBySideDiff('hostname r1\nip 10.0.0.1\n', 'hostname r1\nip 10.0.0.2\n')

    expect(modified?.kind).toBe('modified')
    expect(modified?.leftSegments?.filter((s) => s.changed).map((s) => s.text)).toEqual(['1'])
    expect(modified?.rightSegments?.filter((s) => s.changed).map((s) => s.text)).toEqual(['2'])
  })

  it('keeps unpaired lines as pure additions and removals without shifting numbering', () => {
    const rows = sideBySideDiff('a\nb\nc\n', 'a\nx\ny\nc\n')

    expect(rows.map((r) => r.kind)).toEqual(['equal', 'modified', 'added', 'equal'])
    expect(rows[2]).toMatchObject({ left: null, right: 'y', leftNumber: null, rightNumber: 3 })
    expect(rows[3]).toMatchObject({ leftNumber: 3, rightNumber: 4 })
  })

  it('handles files without a trailing newline', () => {
    expect(summarise(sideBySideDiff('a\nb', 'a\nb\nc'))).toEqual({ added: 1, removed: 0, modified: 1 })
  })

  it('treats markup as plain text', () => {
    const [row] = sideBySideDiff('<script>alert(1)</script>\n', 'x\n')

    expect(row?.left).toBe('<script>alert(1)</script>')
  })

  it('diffs large similar configurations quickly', () => {
    const base = Array.from({ length: 50_000 }, (_, i) => `interface ge-0/0/${i} description port ${i}`)
    const changed = [...base]
    changed[25_000] = 'interface ge-0/0/25000 description CHANGED'

    const started = performance.now()
    const summary = summarise(sideBySideDiff(base.join('\n'), changed.join('\n')))

    expect(summary).toEqual({ added: 0, removed: 0, modified: 1 })
    expect(performance.now() - started).toBeLessThan(5_000)
  })
})
