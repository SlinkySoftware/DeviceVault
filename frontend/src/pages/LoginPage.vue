<!-- SPDX-License-Identifier: GPL-3.0-or-later -->
<template>
  <q-page class="login-page flex flex-center">
    <q-card class="login-card q-pa-lg">
      <div class="text-center q-mb-lg">
        <img src="/logos/dv-mini-logo.png" alt="" class="login-logo" />
        <h1 class="text-h4 q-my-sm">DeviceVault</h1>
        <div class="text-muted">Device Backup Management System</div>
      </div>

      <q-banner v-if="error" dense rounded class="bg-negative text-white q-mb-md">
        <template #avatar><q-icon name="error" /></template>
        {{ error }}
      </q-banner>

      <q-form class="q-gutter-md" @submit="submit">
        <q-input
          v-model="username"
          label="Username"
          outlined
          autocomplete="username"
          autofocus
          :disable="loading"
          :rules="[(v: string) => !!v || 'Username is required']"
        >
          <template #prepend><q-icon name="person" /></template>
        </q-input>
        <q-input
          v-model="password"
          :type="showPassword ? 'text' : 'password'"
          label="Password"
          outlined
          autocomplete="current-password"
          :disable="loading"
          :rules="[(v: string) => !!v || 'Password is required']"
        >
          <template #prepend><q-icon name="lock" /></template>
          <template #append>
            <q-icon
              :name="showPassword ? 'visibility_off' : 'visibility'"
              class="cursor-pointer"
              :aria-label="showPassword ? 'Hide password' : 'Show password'"
              @click="showPassword = !showPassword"
            />
          </template>
        </q-input>
        <q-checkbox v-model="remember" label="Remember my username" />
        <q-btn type="submit" color="primary" label="Log in" size="lg" class="full-width" :loading="loading" />
      </q-form>
    </q-card>
  </q-page>
</template>

<script setup lang="ts">
import { ref } from 'vue'
import { useRoute, useRouter } from 'vue-router'

import { apiErrorMessage } from '@/api/client'
import { safeRedirect } from '@/router/guard'
import { useAuthStore } from '@/stores/auth'

const auth = useAuthStore()
const route = useRoute()
const router = useRouter()

const username = ref(auth.rememberedUsername)
const remember = ref(!!auth.rememberedUsername)
const password = ref('')
const showPassword = ref(false)
const loading = ref(false)
const error = ref('')

async function submit(): Promise<void> {
  error.value = ''
  loading.value = true
  try {
    await auth.login(username.value, password.value, remember.value)
    await router.replace(safeRedirect(route.query.redirect))
  } catch (exc) {
    password.value = ''
    error.value = apiErrorMessage(exc, 'Login failed. Please check your credentials.')
  } finally {
    loading.value = false
  }
}
</script>

<style scoped>
.login-page {
  min-height: 100vh;
  background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
}

body.body--dark .login-page {
  background: radial-gradient(circle at 30% 20%, #2d2d2d 0%, #1e1e1e 70%);
}

.login-card {
  width: 100%;
  max-width: 420px;
}

.login-logo {
  max-width: 96px;
}
</style>
