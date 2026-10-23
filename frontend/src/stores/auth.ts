// SPDX-License-Identifier: GPL-3.0-or-later
import { acceptHMRUpdate, defineStore } from 'pinia'
import { computed, ref } from 'vue'

import { TOKEN_KEY } from '@/api/client'
import { authApi } from '@/api/endpoints'
import type { CurrentUser } from '@/api/types'
import { readJson, readString, remove, writeJson, writeString } from '@/utils/storage'

const USER_KEY = 'user'
const REMEMBERED_USERNAME_KEY = 'rememberedUsername'

export const useAuthStore = defineStore('auth', () => {
  const token = ref<string | null>(readString(TOKEN_KEY))
  // Cached so the menu renders immediately; refreshed from the API on load.
  const user = ref<CurrentUser | null>(token.value ? readJson<CurrentUser>(USER_KEY) : null)

  const isAuthenticated = computed(() => token.value !== null)
  const isAdmin = computed(() => !!user.value && (user.value.is_staff || user.value.is_superuser))
  const isSuperuser = computed(() => !!user.value?.is_superuser)
  const rememberedUsername = ref(readString(REMEMBERED_USERNAME_KEY) ?? '')

  async function fetchUser(): Promise<CurrentUser> {
    const current = await authApi.currentUser()
    user.value = current
    writeJson(USER_KEY, current)
    return current
  }

  async function login(username: string, password: string, remember: boolean): Promise<void> {
    const response = await authApi.login(username, password)
    token.value = response.token
    writeString(TOKEN_KEY, response.token)
    if (remember) {
      rememberedUsername.value = username
      writeString(REMEMBERED_USERNAME_KEY, username)
    } else {
      rememberedUsername.value = ''
      remove(REMEMBERED_USERNAME_KEY)
    }
    await fetchUser()
  }

  /** Forget the session locally (no API call). */
  function clear(): void {
    token.value = null
    user.value = null
    remove(TOKEN_KEY)
    remove(USER_KEY)
  }

  async function logout(): Promise<void> {
    try {
      await authApi.logout()
    } catch {
      // The token may already be invalid; the local session is cleared regardless.
    }
    clear()
  }

  return {
    token,
    user,
    isAuthenticated,
    isAdmin,
    isSuperuser,
    rememberedUsername,
    fetchUser,
    login,
    logout,
    clear,
  }
})

if (import.meta.hot) import.meta.hot.accept(acceptHMRUpdate(useAuthStore, import.meta.hot))
