// SPDX-License-Identifier: GPL-3.0-or-later
import { describe, expect, it } from 'vitest'

import { splitSecretTokens } from './search'

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
