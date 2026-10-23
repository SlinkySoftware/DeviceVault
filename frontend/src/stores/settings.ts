// SPDX-License-Identifier: GPL-3.0-or-later
import { acceptHMRUpdate, defineStore } from 'pinia'
import { ref } from 'vue'

import { settingsApi } from '@/api/endpoints'
import { setDisplayTimeZone } from '@/utils/datetime'

export const useSettingsStore = defineStore('settings', () => {
  /** The orchestrator's display timezone (DV_TIMEZONE); null until loaded. */
  const timeZone = ref<string | null>(null)

  async function loadTimeZone(): Promise<void> {
    try {
      timeZone.value = await settingsApi.timezone()
    } catch {
      timeZone.value = null
    }
    setDisplayTimeZone(timeZone.value ?? undefined)
  }

  return { timeZone, loadTimeZone }
})

if (import.meta.hot) import.meta.hot.accept(acceptHMRUpdate(useSettingsStore, import.meta.hot))
