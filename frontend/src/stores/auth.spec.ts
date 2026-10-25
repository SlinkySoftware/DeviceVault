// SPDX-License-Identifier: GPL-3.0-or-later
import { createPinia, setActivePinia } from 'pinia'
import { beforeEach, describe, expect, it, vi } from 'vitest'

import { authApi } from '@/api/endpoints'
import type { CurrentUser } from '@/api/types'

import { useAuthStore } from './auth'
import { useSearchStore } from './search'

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
  config_search: false,
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

  it('offers config search only when it is on and the user may read some backups', async () => {
    const auth = useAuthStore()
    await auth.login('alice', 'pw', false)
    expect(auth.searchAvailable).toBe(false)

    vi.mocked(authApi.login).mockResolvedValue({ user: { ...USER, config_search: true } })
    await auth.login('alice', 'pw', false)
    expect(auth.searchAvailable).toBe(true)

    vi.mocked(authApi.login).mockResolvedValue({ user: { ...USER, config_search: true, grants: { '3': ['view'] } } })
    await auth.login('alice', 'pw', false)
    expect(auth.searchAvailable).toBe(false)
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

  it("returns the identity provider's sign-out URL when the API names one", async () => {
    const auth = useAuthStore()
    await auth.login('alice', 'pw', false)
    vi.mocked(authApi.logout).mockResolvedValue({ redirect: 'https://idp.example.com/logout?x=1' })

    expect(await auth.logout()).toBe('https://idp.example.com/logout?x=1')
    expect(auth.isAuthenticated).toBe(false)
  })

  it('forgets the last config search on logout', async () => {
    const auth = useAuthStore()
    await auth.login('alice', 'pw', false)
    const search = useSearchStore()
    search.form.q = 'snmp-server community public'

    await auth.logout()

    expect(search.form.q).toBe('')
    expect(search.reply).toBeNull()
  })

  it('keeps nothing about the session in browser storage', async () => {
    await useAuthStore().login('alice', 'pw', false)

    expect(Object.keys(localStorage)).toEqual([])
  })
})
