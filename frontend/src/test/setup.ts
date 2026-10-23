// SPDX-License-Identifier: GPL-3.0-or-later
import { config } from '@vue/test-utils'
import { Dialog, Notify, Quasar } from 'quasar'
import { afterEach } from 'vitest'

config.global.plugins = [[Quasar, { plugins: { Dialog, Notify } }]]

afterEach(() => {
  window.localStorage.clear()
})
