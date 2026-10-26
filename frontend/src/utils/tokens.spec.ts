// SPDX-License-Identifier: GPL-3.0-or-later
import { describe, expect, it } from 'vitest'

import { parseNetworks } from './tokens'

describe('parseNetworks', () => {
  it('splits on lines, commas and spaces', () => {
    expect(parseNetworks('192.0.2.0/24\n198.51.100.7, 2001:db8::/32  10.0.0.1')).toEqual([
      '192.0.2.0/24',
      '198.51.100.7',
      '2001:db8::/32',
      '10.0.0.1',
    ])
  })

  it('drops blanks and repeats', () => {
    expect(parseNetworks('\n 192.0.2.1 \n\n192.0.2.1,')).toEqual(['192.0.2.1'])
  })

  it('is empty for no text', () => {
    expect(parseNetworks('   ')).toEqual([])
  })
})
