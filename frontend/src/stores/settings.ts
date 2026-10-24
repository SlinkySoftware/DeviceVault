// SPDX-License-Identifier: GPL-3.0-or-later
import { acceptHMRUpdate, defineStore } from 'pinia'
import { ref } from 'vue'

import { settingsApi } from '@/api/endpoints'
import { setDisplayTimeZone } from '@/utils/datetime'

export const useSettingsStore = defineStore('settings', () => {
  /** The orchestrator's display timezone (DV_TIMEZONE); null until loaded. */
  const timeZone = ref<string | null>(null)
  /** The orchestrator's release version; null until loaded. */
  const version = ref<string | null>(null)

  async function loadTimeZone(): Promise<void> {
    try {
      timeZone.value = await settingsApi.timezone()
    } catch {
      timeZone.value = null
    }
    setDisplayTimeZone(timeZone.value ?? undefined)
  }

  async function loadVersion(): Promise<void> {
    if (version.value) return
    try {
      version.value = await settingsApi.version()
    } catch {
      version.value = null
    }
  }

  return { timeZone, loadTimeZone, version, loadVersion }
})

if (import.meta.hot) import.meta.hot.accept(acceptHMRUpdate(useSettingsStore, import.meta.hot))
