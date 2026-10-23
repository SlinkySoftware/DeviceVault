// SPDX-License-Identifier: GPL-3.0-or-later
import { acceptHMRUpdate, defineStore } from 'pinia'
import { Dark } from 'quasar'
import { ref } from 'vue'

import { authApi } from '@/api/endpoints'
import type { ThemeMode } from '@/api/types'
import { readString, writeString } from '@/utils/storage'

const MODE_KEY = 'userTheme'

export const useThemeStore = defineStore('theme', () => {
  const mode = ref<ThemeMode>(readString(MODE_KEY) === 'light' ? 'light' : 'dark')

  function applyMode(next: ThemeMode): void {
    mode.value = next
    writeString(MODE_KEY, next)
    Dark.set(next === 'dark')
  }

  /** Apply the cached mode immediately, before anything is fetched. */
  function init(): void {
    applyMode(mode.value)
  }

  /** The signed-in user's light/dark preference. */
  async function loadPreference(): Promise<void> {
    try {
      applyMode((await authApi.preferences()).theme)
    } catch {
      // Keep the cached mode.
    }
  }

  async function savePreference(next: ThemeMode): Promise<void> {
    await authApi.updatePreferences({ theme: next })
    applyMode(next)
  }

  return { mode, init, loadPreference, savePreference }
})

if (import.meta.hot) import.meta.hot.accept(acceptHMRUpdate(useThemeStore, import.meta.hot))
