// SPDX-License-Identifier: GPL-3.0-or-later
// https://v2.quasar.dev/quasar-cli-vite/quasar-config-file

import { defineConfig } from '#q-app'

// The API is same-origin under /api: nginx proxies it in production, and the
// dev server proxies it here (DV_DEV_API_TARGET, default the local runserver).
const apiTarget = process.env.DV_DEV_API_TARGET || 'http://localhost:8000'

export default defineConfig(() => ({
  boot: ['session'],
  css: ['app.css'],
  extras: ['material-icons'],

  build: {
    target: { browser: ['es2022', 'firefox115', 'chrome115', 'safari15'] },
    vueRouterMode: 'history',
    // Every component uses <script setup>; dropping the Options API shrinks the bundle.
    vueOptionsAPI: false,
    typescript: { strict: true, vueShim: true },
  },

  devServer: {
    port: 9000,
    host: '0.0.0.0',
    open: false,
    allowedHosts: true,
    proxy: Object.fromEntries(['/api', '/admin', '/static'].map((prefix) => [prefix, { target: apiTarget }])),
  },

  framework: {
    config: {},
    plugins: ['Notify', 'Dialog'],
  },
}))
