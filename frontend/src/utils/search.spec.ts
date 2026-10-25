// SPDX-License-Identifier: GPL-3.0-or-later
import { describe, expect, it } from 'vitest'

import { highlightLine, highlightPattern, splitSecretTokens } from './search'

const TOKEN = `{{secret:${'0a'.repeat(16)}}}`

describe('splitSecretTokens', () => {
  it('separates tokens from the text around them', () => {
    expect(splitSecretTokens(`snmp-server community ${TOKEN} RO`)).toEqual([
      { text: 'snmp-server community ', secret: false },
      { text: TOKEN, secret: true },
      { text: ' RO', secret: false },
    ])
  })

  it('handles several tokens and lines with none', () => {
    expect(splitSecretTokens(`${TOKEN}${TOKEN}`).map((s) => s.secret)).toEqual([true, true])
    expect(splitSecretTokens(' shutdown')).toEqual([{ text: ' shutdown', secret: false }])
    expect(splitSecretTokens('')).toEqual([{ text: '', secret: false }])
  })

  it('leaves look-alikes as text', () => {
    expect(splitSecretTokens('{{secret:nothex}}')).toEqual([{ text: '{{secret:nothex}}', secret: false }])
  })
})

describe('highlightLine', () => {
  const marked = (line: string, mode: 'text' | 'regex' | 'secret', query: string) =>
    highlightLine(line, highlightPattern(mode, query))
      .filter((segment) => segment.match)
      .map((segment) => segment.text)

  it('marks every case-insensitive occurrence of the text', () => {
    expect(marked('interface Gi0/1 description GI uplink', 'text', 'gi')).toEqual(['Gi', 'GI'])
    expect(highlightLine('ip a.b', highlightPattern('text', 'a.b')).map((s) => s.text)).toEqual(['ip ', 'a.b'])
  })

  it('marks regex matches, and nothing for patterns JavaScript rejects', () => {
    expect(marked('vlan 10 name users', 'regex', 'vlan \\d+')).toEqual(['vlan 10'])
    expect(marked('vlan 10', 'regex', '(?P<id>\\d+')).toEqual([])
    expect(marked('anything', 'regex', '^')).toEqual([])
  })

  it('marks a secret chip a match covers, and never a secret search', () => {
    const segments = highlightLine(`snmp-server community ${TOKEN} RO`, highlightPattern('regex', 'community \\S+'))
    expect(segments.map((s) => [s.text === TOKEN ? 'token' : s.text, !!s.match])).toEqual([
      ['snmp-server ', false],
      ['community ', true],
      ['token', true],
      [' RO', false],
    ])
    expect(highlightPattern('secret', 'hunter2')).toBeNull()
  })
})
