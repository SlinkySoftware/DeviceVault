// SPDX-License-Identifier: GPL-3.0-or-later
// The signed-in user. The session itself is an HttpOnly cookie the app cannot
// read, so "signed in" means the API returned the current user.
import { acceptHMRUpdate, defineStore } from 'pinia'
import { computed, ref } from 'vue'

import { authApi } from '@/api/endpoints'
import type { CurrentUser, GrantFlag, Id } from '@/api/types'
import { readString, remove, writeString } from '@/utils/storage'

import { useSearchStore } from './search'

const REMEMBERED_USERNAME_KEY = 'rememberedUsername'

export const useAuthStore = defineStore('auth', () => {
  const user = ref<CurrentUser | null>(null)

  const isAuthenticated = computed(() => user.value !== null)
  const isGlobalAdmin = computed(() => !!user.value?.is_global_admin)
  /** Global administrators and administrators of at least one device group. */
  const administersAny = computed(
    () => isGlobalAdmin.value || Object.values(user.value?.grants ?? {}).some((flags) => flags.includes('admin')),
  )
  /** Config search is on and the user may read some device's backups. */
  const searchAvailable = computed(
    () =>
      !!user.value?.config_search &&
      (isGlobalAdmin.value || Object.values(user.value.grants).some((flags) => flags.includes('view_contents'))),
  )
  const rememberedUsername = ref(readString(REMEMBERED_USERNAME_KEY) ?? '')

  /** Whether the user holds `flag` on a device group (null: ungrouped, global administrators only). */
  function can(flag: GrantFlag, deviceGroup: Id | null | undefined): boolean {
    if (isGlobalAdmin.value) return true
    if (deviceGroup === null || deviceGroup === undefined) return false
    return user.value?.grants[String(deviceGroup)]?.includes(flag) ?? false
  }

  async function fetchUser(): Promise<CurrentUser> {
    const current = await authApi.currentUser()
    user.value = current
    return current
  }

  async function login(username: string, password: string, remember: boolean): Promise<void> {
    await authApi.csrf()
    user.value = (await authApi.login(username, password)).user
    if (remember) {
      rememberedUsername.value = username
      writeString(REMEMBERED_USERNAME_KEY, username)
    } else {
      rememberedUsername.value = ''
      remove(REMEMBERED_USERNAME_KEY)
    }
  }

  /** Forget the user locally (no API call), and what they searched for. */
  function clear(): void {
    user.value = null
    useSearchStore().clear()
  }

  /** Signs out; returns the identity provider's sign-out URL to visit, if the session came from one that asks. */
  async function logout(): Promise<string | null> {
    let redirect: string | null = null
    try {
      redirect = (await authApi.logout()).redirect ?? null
    } catch {
      // The session may already have ended; the local state is cleared regardless.
    }
    clear()
    return redirect
  }

  return {
    user,
    isAuthenticated,
    isGlobalAdmin,
    administersAny,
    searchAvailable,
    rememberedUsername,
    can,
    fetchUser,
    login,
    logout,
    clear,
  }
})

if (import.meta.hot) import.meta.hot.accept(acceptHMRUpdate(useAuthStore, import.meta.hot))
