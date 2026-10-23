// SPDX-License-Identifier: GPL-3.0-or-later
import { defineRouter } from '#q-app'
import { createRouter, createWebHistory } from 'vue-router'

import { useAuthStore } from '@/stores/auth'

import { createAuthGuard } from './guard'
import routes from './routes'

export default defineRouter(({ store }) => {
  const router = createRouter({
    history: createWebHistory(process.env.VUE_ROUTER_BASE),
    routes,
    scrollBehavior: () => ({ left: 0, top: 0 }),
  })

  router.beforeEach(createAuthGuard(() => useAuthStore(store)))
  router.afterEach((to) => {
    document.title = to.meta.title ? `${to.meta.title} · DeviceVault` : 'DeviceVault'
  })

  return router
})
