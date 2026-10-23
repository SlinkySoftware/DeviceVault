// SPDX-License-Identifier: GPL-3.0-or-later
import { acceptHMRUpdate, defineStore } from 'pinia'
import { Dark } from 'quasar'
import { ref } from 'vue'

import { authApi, settingsApi } from '@/api/endpoints'
import type { ThemeColors, ThemeMode } from '@/api/types'
import { readString, writeString } from '@/utils/storage'

const MODE_KEY = 'userTheme'

export const DEFAULT_COLORS: Readonly<ThemeColors> = {
  title_bar_color: '#1976D2',
  dashboard_box_color: '#1976D2',
  dashboard_nested_box_color: '#2196F3',
}

const CSS_VARIABLES: Record<keyof ThemeColors, string> = {
  title_bar_color: '--theme-title-bar',
  dashboard_box_color: '--theme-dashboard-box',
  dashboard_nested_box_color: '--theme-dashboard-nested-box',
}

function applyColors(colors: ThemeColors): void {
  for (const [key, variable] of Object.entries(CSS_VARIABLES) as [keyof ThemeColors, string][]) {
    document.documentElement.style.setProperty(variable, colors[key])
  }
}

export const useThemeStore = defineStore('theme', () => {
  const colors = ref<ThemeColors>({ ...DEFAULT_COLORS })
  const mode = ref<ThemeMode>(readString(MODE_KEY) === 'light' ? 'light' : 'dark')

  function applyMode(next: ThemeMode): void {
    mode.value = next
    writeString(MODE_KEY, next)
    Dark.set(next === 'dark')
  }

  /** Apply cached settings immediately, before anything is fetched. */
  function init(): void {
    applyColors(colors.value)
    applyMode(mode.value)
  }

  /** Application-wide colours (readable without logging in). */
  async function loadColors(): Promise<void> {
    try {
      colors.value = { ...DEFAULT_COLORS, ...(await settingsApi.theme()) }
    } catch {
      colors.value = { ...DEFAULT_COLORS }
    }
    applyColors(colors.value)
  }

  async function saveColors(next: ThemeColors): Promise<void> {
    colors.value = await settingsApi.updateTheme(next)
    applyColors(colors.value)
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

  return { colors, mode, init, loadColors, saveColors, loadPreference, savePreference }
})

if (import.meta.hot) import.meta.hot.accept(acceptHMRUpdate(useThemeStore, import.meta.hot))
