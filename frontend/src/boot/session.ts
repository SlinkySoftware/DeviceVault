// SPDX-License-Identifier: GPL-3.0-or-later
// Ties API authentication failures to the session: any 401 drops the local
// session and sends the user to the login page, returning them afterwards.

import { defineBoot } from '#q-app'

import { setUnauthorizedHandler } from '@/api/client'
import { useAuthStore } from '@/stores/auth'
import { useThemeStore } from '@/stores/theme'

export default defineBoot(({ router, store }) => {
  useThemeStore(store).init()

  setUnauthorizedHandler(() => {
    const auth = useAuthStore(store)
    if (!auth.isAuthenticated) return
    auth.clear()
    const current = router.currentRoute.value
    if (current.name !== 'login') {
      void router.push({ name: 'login', query: current.fullPath === '/' ? {} : { redirect: current.fullPath } })
    }
  })
})
