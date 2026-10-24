// SPDX-License-Identifier: GPL-3.0-or-later
import { describe, expect, it, vi } from 'vitest'
import type { RouteLocationNormalized } from 'vue-router'

import type { CurrentUser } from '@/api/types'
import type { useAuthStore } from '@/stores/auth'

import { createAuthGuard, safeRedirect } from './guard'

type AuthStore = ReturnType<typeof useAuthStore>

const MEMBER = { is_global_admin: false, grants: { '1': ['view'] } } as unknown as CurrentUser
const GROUP_ADMIN = { is_global_admin: false, grants: { '1': ['view', 'admin'] } } as unknown as CurrentUser
const GLOBAL_ADMIN = { is_global_admin: true, grants: {} } as unknown as CurrentUser

/** A fake store; `session` is who the API reports as signed in (null: nobody). */
function fakeAuth(user: CurrentUser | null, session: CurrentUser | null = user): AuthStore {
  const auth = {
    user,
    get isAuthenticated() {
      return this.user !== null
    },
    get isGlobalAdmin() {
      return !!this.user?.is_global_admin
    },
    get administersAny() {
      return !!this.user && (this.user.is_global_admin || Object.values(this.user.grants).some((f) => f.includes('admin')))
    },
    fetchUser: vi.fn(async () => {
      if (!session) throw new Error('401')
      auth.user = session
      return session
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
  it('sends users without a session to login, remembering where they were going', async () => {
    expect(await navigate(fakeAuth(null), route('/devices'))).toEqual({
      name: 'login',
      query: { redirect: '/devices' },
    })
  })

  it('picks up an existing session after a reload', async () => {
    const auth = fakeAuth(null, MEMBER)

    expect(await navigate(auth, route('/devices'))).toBe(true)
    expect(auth.fetchUser).toHaveBeenCalledOnce()
  })

  it('lets anyone reach public routes without asking the API', async () => {
    const auth = fakeAuth(null)

    expect(await navigate(auth, route('/login', { public: true }, 'login'))).toBe(true)
    expect(auth.fetchUser).not.toHaveBeenCalled()
  })

  it('keeps group administrators out of global admin routes', async () => {
    expect(await navigate(fakeAuth(GROUP_ADMIN), route('/vaultadmin/users', { requiresGlobalAdmin: true }))).toEqual({
      name: 'dashboard',
    })
  })

  it('lets group administrators reach group admin routes, but not members', async () => {
    const credentials = route('/vaultadmin/credentials', { requiresGroupAdmin: true })

    expect(await navigate(fakeAuth(GROUP_ADMIN), credentials)).toBe(true)
    expect(await navigate(fakeAuth(MEMBER), credentials)).toEqual({ name: 'dashboard' })
  })

  it('lets global administrators everywhere', async () => {
    expect(await navigate(fakeAuth(GLOBAL_ADMIN), route('/vaultadmin/workers', { requiresGlobalAdmin: true }))).toBe(
      true,
    )
  })
})
