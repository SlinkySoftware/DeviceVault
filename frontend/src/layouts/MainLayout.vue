<!-- SPDX-License-Identifier: GPL-3.0-or-later -->
<template>
  <q-layout view="hHh lpR fFf">
    <q-header elevated class="text-white" :style="{ backgroundColor: theme.colors.title_bar_color }">
      <q-toolbar>
        <q-btn flat dense round icon="menu" aria-label="Toggle menu" class="lt-md" @click="drawerOpen = !drawerOpen" />
        <q-toolbar-title class="row items-center no-wrap">
          <img src="/logos/dv-mini-logo.png" alt="" class="logo-mini q-mr-sm" />
          <span>DeviceVault</span>
        </q-toolbar-title>
        <q-btn-dropdown flat dense no-caps icon="person" :label="auth.user?.username ?? 'Account'">
          <q-list style="min-width: 180px">
            <q-item v-close-popup clickable :to="{ name: 'profile' }">
              <q-item-section avatar><q-icon name="account_circle" /></q-item-section>
              <q-item-section>Profile</q-item-section>
            </q-item>
            <q-separator />
            <q-item v-close-popup clickable @click="logout">
              <q-item-section avatar><q-icon name="logout" /></q-item-section>
              <q-item-section>Logout</q-item-section>
            </q-item>
          </q-list>
        </q-btn-dropdown>
      </q-toolbar>
    </q-header>

    <q-drawer v-model="drawerOpen" show-if-above side="left" bordered>
      <q-list class="nav">
        <q-item v-for="link in MAIN_LINKS" :key="link.to" clickable :to="link.to" :exact="link.to === '/'">
          <q-item-section avatar><q-icon :name="link.icon" /></q-item-section>
          <q-item-section>{{ link.label }}</q-item-section>
        </q-item>

        <q-expansion-item
          v-if="auth.isAdmin"
          icon="admin_panel_settings"
          label="Admin Settings"
          header-class="nav-section"
          :default-opened="onAdminRoute"
        >
          <q-expansion-item
            v-for="section in adminSections"
            :key="section.label"
            :icon="section.icon"
            :label="section.label"
            dense
            dense-toggle
            header-class="nav-section nav-level-1"
            :default-opened="section.links.some((link) => route.path.startsWith(link.to))"
          >
            <q-list class="nav-items">
              <q-item v-for="link in section.links" :key="link.to" clickable dense :to="link.to" class="nav-item">
                <q-item-section avatar><q-icon :name="link.icon" size="xs" /></q-item-section>
                <q-item-section>{{ link.label }}</q-item-section>
              </q-item>
            </q-list>
          </q-expansion-item>
        </q-expansion-item>
      </q-list>
    </q-drawer>

    <q-page-container>
      <router-view />
    </q-page-container>
  </q-layout>
</template>

<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'
import { useRoute, useRouter } from 'vue-router'

import { useNotify } from '@/composables/useNotify'
import { useAuthStore } from '@/stores/auth'
import { useSettingsStore } from '@/stores/settings'
import { useThemeStore } from '@/stores/theme'

import { ADMIN_SECTIONS, MAIN_LINKS } from './navigation'

const auth = useAuthStore()
const theme = useThemeStore()
const settings = useSettingsStore()
const route = useRoute()
const router = useRouter()
const notify = useNotify()

const drawerOpen = ref(false)
const adminSections = computed(() => ADMIN_SECTIONS.filter((section) => !section.superuserOnly || auth.isSuperuser))
const onAdminRoute = computed(() => route.path.startsWith('/vaultadmin/'))

async function logout(): Promise<void> {
  await auth.logout()
  notify.info('Logged out')
  await router.push({ name: 'login' })
}

onMounted(() => {
  void theme.loadColors()
  void theme.loadPreference()
  void settings.loadTimeZone()
  // Refresh cached permissions in the background.
  auth.fetchUser().catch(() => undefined)
})
</script>

<style scoped>
.logo-mini {
  height: 28px;
  width: auto;
}

.nav :deep(.q-item) {
  color: #479aee;
}

body.body--dark .nav :deep(.q-item) {
  color: #42a5f5;
}

.nav :deep(.nav-section) {
  color: #757575;
}

body.body--dark .nav :deep(.nav-section) {
  color: #e0e0e0;
}

.nav :deep(.nav-level-1) {
  padding-left: 24px;
}

.nav-items {
  background-color: rgba(0, 0, 0, 0.04);
}

body.body--dark .nav-items {
  background-color: rgba(255, 255, 255, 0.03);
}

.nav-item {
  padding-left: 40px;
}

.nav :deep(.q-item.q-router-link--active) {
  background-color: #1565c0;
  color: #fff;
}

body.body--dark .nav :deep(.q-item.q-router-link--active) {
  background-color: #0d47a1;
}
</style>
