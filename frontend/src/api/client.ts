// SPDX-License-Identifier: GPL-3.0-or-later
// HTTP client for the orchestrator API, always served same-origin under /api
// (nginx in production, the Quasar dev-server proxy in development).
// Authentication is the server's HttpOnly session cookie; unsafe requests echo
// Django's CSRF cookie in X-CSRFToken (axios does this for same-origin calls).

import axios from 'axios'

export const http = axios.create({
  baseURL: '/api',
  headers: { 'Content-Type': 'application/json' },
  xsrfCookieName: 'csrftoken',
  xsrfHeaderName: 'X-CSRFToken',
})

let unauthorizedHandler: (() => void) | null = null

/** Called on any 401 response; the auth boot file wires it to logout + redirect. */
export function setUnauthorizedHandler(handler: (() => void) | null): void {
  unauthorizedHandler = handler
}

http.interceptors.response.use(
  (response) => response,
  (error: unknown) => {
    if (axios.isAxiosError(error) && error.response?.status === 401) unauthorizedHandler?.()
    return Promise.reject(error)
  },
)

function flatten(value: unknown): string {
  if (typeof value === 'string') return value.trim()
  if (Array.isArray(value)) return value.map(flatten).filter(Boolean).join(' ')
  return ''
}

/**
 * The most useful human-readable message in an API error.
 *
 * Handles DRF's shapes: `{detail}`, `{error}`, `{non_field_errors: [...]}` and
 * field errors (`{name: ["This field is required."]}`).
 */
export function apiErrorMessage(error: unknown, fallback: string): string {
  if (!axios.isAxiosError(error)) return fallback
  const data: unknown = error.response?.data
  if (typeof data === 'string') {
    const text = data.trim()
    // Ignore HTML error pages from proxies or Django's debug view.
    return text && !text.startsWith('<') && text.length < 300 ? text : fallback
  }
  if (data && typeof data === 'object') {
    const record = data as Record<string, unknown>
    for (const key of ['detail', 'error', 'message', 'non_field_errors']) {
      const message = flatten(record[key])
      if (message) return message
    }
    for (const [key, value] of Object.entries(record)) {
      const message = flatten(value)
      if (message) return `${key.replaceAll('_', ' ')}: ${message}`
    }
  }
  return fallback
}
