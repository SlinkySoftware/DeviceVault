<!-- SPDX-License-Identifier: GPL-3.0-or-later -->
<template>
  <q-page padding>
    <q-card style="max-width: 720px">
      <q-card-section class="row items-center">
        <q-avatar size="64px" color="primary" text-color="white" class="q-mr-md">
          {{ initials }}
        </q-avatar>
        <div>
          <div class="text-h6">{{ auth.user?.username }}</div>
          <div class="text-subtitle2">{{ fullName }}</div>
          <div v-if="!editable" class="text-caption text-grey">Managed by an external identity provider</div>
        </div>
      </q-card-section>
      <q-separator />

      <q-card-section>
        <div class="text-subtitle1 q-mb-sm">Details</div>
        <q-form class="q-gutter-md" @submit="saveDetails">
          <q-input :model-value="auth.user?.username" label="Username" disable />
          <q-input v-model="details.email" label="Email" type="email" :disable="!editable" />
          <q-input v-model="details.first_name" label="First name" :disable="!editable" />
          <q-input v-model="details.last_name" label="Last name" :disable="!editable" />
          <q-btn v-if="editable" type="submit" color="primary" label="Save" :loading="savingDetails" />
        </q-form>
      </q-card-section>
      <q-separator />

      <q-card-section>
        <div class="text-subtitle1 q-mb-sm">Appearance</div>
        <q-btn-toggle
          :model-value="theme.mode"
          :options="[
            { label: 'Dark', value: 'dark', icon: 'dark_mode' },
            { label: 'Light', value: 'light', icon: 'light_mode' },
          ]"
          no-caps
          toggle-color="primary"
          @update:model-value="saveTheme"
        />
      </q-card-section>

      <template v-if="editable">
        <q-separator />
        <q-card-section>
          <div class="text-subtitle1 q-mb-sm">Change password</div>
          <q-form ref="passwordForm" class="q-gutter-md" @submit="changePassword">
            <q-input
              v-model="passwords.current"
              type="password"
              label="Current password"
              autocomplete="current-password"
              :rules="[required]"
            />
            <q-input
              v-model="passwords.next"
              type="password"
              label="New password"
              autocomplete="new-password"
              :rules="[required]"
            />
            <q-input
              v-model="passwords.confirm"
              type="password"
              label="Confirm new password"
              autocomplete="new-password"
              :rules="[required, (v: string) => v === passwords.next || 'Passwords do not match']"
            />
            <q-btn type="submit" color="primary" label="Update password" :loading="savingPassword" />
          </q-form>
        </q-card-section>
      </template>
    </q-card>
  </q-page>
</template>

<script setup lang="ts">
import type { QForm } from 'quasar'
import { computed, reactive, ref, watch } from 'vue'

import { authApi } from '@/api/endpoints'
import type { ThemeMode, UserDetails } from '@/api/types'
import { useNotify } from '@/composables/useNotify'
import { useAuthStore } from '@/stores/auth'
import { useThemeStore } from '@/stores/theme'

const auth = useAuthStore()
const theme = useThemeStore()
const notify = useNotify()

const editable = computed(() => auth.user?.editable ?? false)
const details = reactive<UserDetails>({ email: '', first_name: '', last_name: '' })
const fullName = computed(() => `${details.first_name} ${details.last_name}`.trim() || auth.user?.username || '')
const initials = computed(() =>
  (fullName.value || '?')
    .split(/\s+/)
    .map((part) => part.charAt(0).toUpperCase())
    .slice(0, 2)
    .join(''),
)

watch(
  () => auth.user,
  (user) => {
    if (user) Object.assign(details, { email: user.email, first_name: user.first_name, last_name: user.last_name })
  },
  { immediate: true },
)

const savingDetails = ref(false)
async function saveDetails(): Promise<void> {
  savingDetails.value = true
  try {
    await authApi.updateCurrentUser({ ...details })
    await auth.fetchUser()
    notify.success('Profile updated')
  } catch (error) {
    notify.error(error, 'Failed to update profile')
  } finally {
    savingDetails.value = false
  }
}

async function saveTheme(mode: ThemeMode): Promise<void> {
  try {
    await theme.savePreference(mode)
  } catch (error) {
    notify.error(error, 'Failed to save theme preference')
  }
}

const required = (value: string) => !!value || 'Required'
const passwordForm = ref<QForm | null>(null)
const passwords = reactive({ current: '', next: '', confirm: '' })
const savingPassword = ref(false)

async function changePassword(): Promise<void> {
  savingPassword.value = true
  try {
    await authApi.changePassword(passwords.current, passwords.next)
    Object.assign(passwords, { current: '', next: '', confirm: '' })
    passwordForm.value?.resetValidation()
    notify.success('Password updated')
  } catch (error) {
    notify.error(error, 'Failed to change password')
  } finally {
    savingPassword.value = false
  }
}
</script>
