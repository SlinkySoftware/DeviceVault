// SPDX-License-Identifier: GPL-3.0-or-later
import type { NavigationGuardWithThis, RouteLocationRaw } from 'vue-router'

import type { useAuthStore } from '@/stores/auth'

type AuthStore = ReturnType<typeof useAuthStore>

/**
 * Only follow same-app redirects after login: a path starting with a single
 * "/" (so not "//evil.example" or "https://...").
 */
export function safeRedirect(value: unknown): string {
  return typeof value === 'string' && value.startsWith('/') && !value.startsWith('//') ? value : '/'
}

/**
 * Route guard: public routes are open, everything else needs a session, and
 * admin areas need the matching role. The session cookie is invisible to the
 * app, so the first protected navigation asks the API who is signed in. The
 * API enforces the same rules; this only keeps users out of pages they cannot use.
 */
export function createAuthGuard(getAuth: () => AuthStore): NavigationGuardWithThis<undefined> {
  return async (to): Promise<true | RouteLocationRaw> => {
    const auth = getAuth()

    if (to.meta.public) {
      return to.name === 'login' && auth.isAuthenticated ? { path: safeRedirect(to.query.redirect) } : true
    }
    if (!auth.isAuthenticated) {
      try {
        await auth.fetchUser()
      } catch {
        auth.clear()
        return { name: 'login', query: to.fullPath === '/' ? {} : { redirect: to.fullPath } }
      }
    }
    if (to.meta.requiresGlobalAdmin && !auth.isGlobalAdmin) return { name: 'dashboard' }
    if (to.meta.requiresGroupAdmin && !auth.administersAny) return { name: 'dashboard' }
    return true
  }
}
