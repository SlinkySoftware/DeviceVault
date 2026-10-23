// SPDX-License-Identifier: GPL-3.0-or-later
import { describe, expect, it, vi } from 'vitest'
import type { RouteLocationNormalized } from 'vue-router'

import type { CurrentUser } from '@/api/types'
import type { useAuthStore } from '@/stores/auth'

import { createAuthGuard, safeRedirect } from './guard'

type AuthStore = ReturnType<typeof useAuthStore>

const ADMIN = { is_staff: true, is_superuser: false } as CurrentUser
const MEMBER = { is_staff: false, is_superuser: false } as CurrentUser

function fakeAuth(user: CurrentUser | null, token: string | null = user ? 'token' : null): AuthStore {
  const auth = {
    token,
    user,
    get isAuthenticated() {
      return this.token !== null
    },
    get isAdmin() {
      return !!this.user && (this.user.is_staff || this.user.is_superuser)
    },
    get isSuperuser() {
      return !!this.user?.is_superuser
    },
    fetchUser: vi.fn(async () => {
      auth.user = MEMBER
      return MEMBER
    }),
    clear: vi.fn(),
  }
  return auth as unknown as AuthStore
}

function route(path: string, meta: RouteLocationNormalized['meta'] = {}, name?: string): RouteLocationNormalized {
  return { path, fullPath: path, meta, name, query: {} } as unknown as RouteLocationNormalized
}

async function navigate(auth: AuthStore, to: RouteLocationNormalized) {
  const guard = createAuthGuard(() => auth)
  return guard.call(undefined, to, route('/'), () => undefined)
}

describe('safeRedirect', () => {
  it.each([
    ['/devices/3', '/devices/3'],
    ['//evil.example/path', '/'],
    ['https://evil.example', '/'],
    [undefined, '/'],
    [['/a', '/b'], '/'],
  ])('%j -> %s', (value, expected) => {
    expect(safeRedirect(value)).toBe(expected)
  })
})

describe('auth guard', () => {
  it('sends anonymous users to login, remembering where they were going', async () => {
    expect(await navigate(fakeAuth(null), route('/devices'))).toEqual({
      name: 'login',
      query: { redirect: '/devices' },
    })
  })

  it('lets anonymous users reach public routes', async () => {
    expect(await navigate(fakeAuth(null), route('/login', { public: true }, 'login'))).toBe(true)
  })

  it('keeps non-admins out of admin routes', async () => {
    expect(await navigate(fakeAuth(MEMBER), route('/vaultadmin/users', { requiresAdmin: true }))).toEqual({
      name: 'dashboard',
    })
  })

  it('keeps admins who are not superusers out of superuser routes', async () => {
    expect(await navigate(fakeAuth(ADMIN), route('/vaultadmin/workers', { requiresSuperuser: true }))).toEqual({
      name: 'dashboard',
    })
  })

  it('loads the user before checking roles when only a token is cached', async () => {
    const auth = fakeAuth(null, 'token')

    expect(await navigate(auth, route('/vaultadmin/users', { requiresAdmin: true }))).toEqual({ name: 'dashboard' })
    expect(auth.fetchUser).toHaveBeenCalledOnce()
  })
})
