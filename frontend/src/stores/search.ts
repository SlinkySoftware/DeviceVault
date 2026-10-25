// SPDX-License-Identifier: GPL-3.0-or-later
// The config search page's last search, kept in memory only: a query may hold a
// secret, so it never goes into the URL (history, access logs) or browser storage.
// Going back from a result's backup shows the same results.
import { acceptHMRUpdate, defineStore } from 'pinia'
import { reactive, ref } from 'vue'

import type { Id, SearchMode, SearchResponse } from '@/api/types'

export interface SearchForm {
  q: string
  mode: SearchMode
  device_group: Id | null
  driver: string | null
}

export const useSearchStore = defineStore('search', () => {
  const form = reactive<SearchForm>({ q: '', mode: 'text', device_group: null, driver: null })
  const reply = ref<SearchResponse | null>(null)

  function clear(): void {
    Object.assign(form, { q: '', mode: 'text', device_group: null, driver: null })
    reply.value = null
  }

  return { form, reply, clear }
})

if (import.meta.hot) import.meta.hot.accept(acceptHMRUpdate(useSearchStore, import.meta.hot))
