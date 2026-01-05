<template>
  <q-layout view="hHh lpR fFf">
    <q-header elevated class="bg-primary text-white">
      <q-toolbar>
        <q-toolbar-title>DeviceVault</q-toolbar-title>
      </q-toolbar>
    </q-header>

    <q-drawer show-if-above side="left" bordered>
      <q-list>
        <q-item clickable to="/" exact>
          <q-item-section avatar>
            <q-icon name="dashboard" />
          </q-item-section>
          <q-item-section>
            <q-item-label>Dashboard</q-item-label>
          </q-item-section>
        </q-item>

        <q-item clickable to="/devices">
          <q-item-section avatar>
            <q-icon name="devices" />
          </q-item-section>
          <q-item-section>
            <q-item-label>Devices</q-item-label>
          </q-item-section>
        </q-item>

        <q-separator v-if="isAdmin" class="q-my-sm" />
        
        <q-item-label v-if="isAdmin" header class="text-grey-8">Admin Settings</q-item-label>
        
        <q-item v-if="isAdmin" clickable to="/admin/device-types">
          <q-item-section avatar>
            <q-icon name="category" />
          </q-item-section>
          <q-item-section>
            <q-item-label>Device Types</q-item-label>
          </q-item-section>
        </q-item>

        <q-item v-if="isAdmin" clickable to="/admin/manufacturers">
          <q-item-section avatar>
            <q-icon name="business" />
          </q-item-section>
          <q-item-section>
            <q-item-label>Manufacturers</q-item-label>
          </q-item-section>
        </q-item>

        <q-item v-if="isAdmin" clickable to="/admin/credentials">
          <q-item-section avatar>
            <q-icon name="vpn_key" />
          </q-item-section>
          <q-item-section>
            <q-item-label>Credentials</q-item-label>
          </q-item-section>
        </q-item>

        <q-item v-if="isAdmin" clickable to="/admin/backup-locations">
          <q-item-section avatar>
            <q-icon name="folder" />
          </q-item-section>
          <q-item-section>
            <q-item-label>Backup Locations</q-item-label>
          </q-item-section>
        </q-item>

        <q-item v-if="isAdmin" clickable to="/admin/retention-policies">
          <q-item-section avatar>
            <q-icon name="schedule" />
          </q-item-section>
          <q-item-section>
            <q-item-label>Retention Policies</q-item-label>
          </q-item-section>
        </q-item>
      </q-list>
    </q-drawer>

    <q-page-container>
      <router-view />
    </q-page-container>
  </q-layout>
</template>

<script setup>
import { ref } from 'vue'
const isAdmin = ref(true)
</script>
