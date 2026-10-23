// SPDX-License-Identifier: GPL-3.0-or-later
import { createPinia, setActivePinia } from 'pinia'
import { beforeEach, describe, expect, it, vi } from 'vitest'

import { authApi } from '@/api/endpoints'
import type { CurrentUser } from '@/api/types'

import { useAuthStore } from './auth'

vi.mock('@/api/endpoints', () => ({
  authApi: { login: vi.fn(), logout: vi.fn(), currentUser: vi.fn() },
}))

const USER = { id: 1, username: 'alice', is_staff: true, is_superuser: false } as CurrentUser

beforeEach(() => {
  setActivePinia(createPinia())
  vi.mocked(authApi.login).mockResolvedValue({ token: 't0k3n', user: USER })
  vi.mocked(authApi.currentUser).mockResolvedValue(USER)
})

describe('auth store', () => {
  it('stores the token and user on login', async () => {
    const auth = useAuthStore()

    await auth.login('alice', 'pw', false)

    expect(auth.isAuthenticated).toBe(true)
    expect(auth.isAdmin).toBe(true)
    expect(localStorage.getItem('authToken')).toBe('t0k3n')
  })

  it('remembers the username only when asked', async () => {
    await useAuthStore().login('alice', 'pw', true)
    expect(localStorage.getItem('rememberedUsername')).toBe('alice')

    await useAuthStore().login('alice', 'pw', false)
    expect(localStorage.getItem('rememberedUsername')).toBeNull()
  })

  it('clears the local session on logout even if the API call fails', async () => {
    const auth = useAuthStore()
    await auth.login('alice', 'pw', false)
    vi.mocked(authApi.logout).mockRejectedValue(new Error('offline'))

    await auth.logout()

    expect(auth.isAuthenticated).toBe(false)
    expect(auth.user).toBeNull()
    expect(localStorage.getItem('authToken')).toBeNull()
  })

  it('restores a cached session on startup', async () => {
    await useAuthStore().login('alice', 'pw', false)

    setActivePinia(createPinia())
    const restored = useAuthStore()

    expect(restored.isAuthenticated).toBe(true)
    expect(restored.user?.username).toBe('alice')
  })
})
