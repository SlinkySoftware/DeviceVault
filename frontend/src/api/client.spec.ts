// SPDX-License-Identifier: GPL-3.0-or-later
import { AxiosError, AxiosHeaders } from 'axios'
import { describe, expect, it } from 'vitest'

import { apiErrorMessage } from './client'

function responseError(status: number, data: unknown): AxiosError {
  const config = { headers: new AxiosHeaders() }
  return new AxiosError('Request failed', 'ERR', config, null, {
    status,
    statusText: '',
    data,
    headers: {},
    config,
  })
}

describe('apiErrorMessage', () => {
  it.each([
    [{ detail: 'Not authorized' }, 'Not authorized'],
    [{ error: 'Device has no device group' }, 'Device has no device group'],
    [{ non_field_errors: ['Invalid credentials.'] }, 'Invalid credentials.'],
    [{ backup_method: ['Unknown backup method "x"'] }, 'backup method: Unknown backup method "x"'],
    ['Plain text error', 'Plain text error'],
  ])('extracts %j', (data, expected) => {
    expect(apiErrorMessage(responseError(400, data), 'fallback')).toBe(expected)
  })

  it('ignores HTML error pages', () => {
    expect(apiErrorMessage(responseError(502, '<html><body>Bad gateway</body></html>'), 'fallback')).toBe('fallback')
  })

  it('falls back for non-HTTP errors', () => {
    expect(apiErrorMessage(new Error('boom'), 'fallback')).toBe('fallback')
  })
})
