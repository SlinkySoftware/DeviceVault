// SPDX-License-Identifier: GPL-3.0-or-later
import { createPinia, setActivePinia } from 'pinia'
import { beforeEach, describe, expect, it, vi } from 'vitest'

import { authApi } from '@/api/endpoints'
import type { CurrentUser } from '@/api/types'

import { useAuthStore } from './auth'

vi.mock('@/api/endpoints', () => ({
  authApi: { csrf: vi.fn(), login: vi.fn(), logout: vi.fn(), currentUser: vi.fn() },
}))

const USER: CurrentUser = {
  id: 1,
  username: 'alice',
  email: '',
  first_name: '',
  last_name: '',
  source: 'local',
  providers: [],
  editable: true,
  is_global_admin: false,
  grants: { '3': ['view', 'backup_now'], '4': ['view', 'backup_now', 'view_contents', 'download', 'admin'] },
}

beforeEach(() => {
  setActivePinia(createPinia())
  vi.mocked(authApi.login).mockResolvedValue({ user: USER })
  vi.mocked(authApi.currentUser).mockResolvedValue(USER)
})

describe('auth store', () => {
  it('gets the CSRF cookie before signing in, and keeps the user', async () => {
    const auth = useAuthStore()

    await auth.login('alice', 'pw', false)

    expect(authApi.csrf).toHaveBeenCalledBefore(vi.mocked(authApi.login))
    expect(auth.isAuthenticated).toBe(true)
    expect(auth.user?.username).toBe('alice')
  })

  it('answers permission questions from the grants', async () => {
    const auth = useAuthStore()
    await auth.login('alice', 'pw', false)

    expect(auth.can('backup_now', 3)).toBe(true)
    expect(auth.can('view_contents', 3)).toBe(false)
    expect(auth.can('view', 99)).toBe(false)
    expect(auth.can('view', null)).toBe(false)
    expect(auth.administersAny).toBe(true)
    expect(auth.isGlobalAdmin).toBe(false)
  })

  it('lets global administrators do anything, including on ungrouped devices', async () => {
    vi.mocked(authApi.login).mockResolvedValue({ user: { ...USER, is_global_admin: true, grants: {} } })
    const auth = useAuthStore()
    await auth.login('alice', 'pw', false)

    expect(auth.can('admin', null)).toBe(true)
    expect(auth.administersAny).toBe(true)
  })

  it('remembers the username only when asked', async () => {
    await useAuthStore().login('alice', 'pw', true)
    expect(localStorage.getItem('rememberedUsername')).toBe('alice')

    await useAuthStore().login('alice', 'pw', false)
    expect(localStorage.getItem('rememberedUsername')).toBeNull()
  })

  it('clears the user on logout even if the API call fails', async () => {
    const auth = useAuthStore()
    await auth.login('alice', 'pw', false)
    vi.mocked(authApi.logout).mockRejectedValue(new Error('offline'))

    await auth.logout()

    expect(auth.isAuthenticated).toBe(false)
    expect(auth.user).toBeNull()
  })

  it('keeps nothing about the session in browser storage', async () => {
    await useAuthStore().login('alice', 'pw', false)

    expect(Object.keys(localStorage)).toEqual([])
  })
})
