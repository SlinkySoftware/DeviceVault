<!-- SPDX-License-Identifier: GPL-3.0-or-later -->
<template>
  <PageCard title="Access" caption="Who holds what on each device group (S View Status, B Backup Now, C View Contents, D Download, A Group Admin)">
    <template #actions>
      <q-btn flat icon="edit" label="User Groups" :to="{ name: 'user-groups' }" />
    </template>

    <div class="row q-col-gutter-md q-mb-md">
      <div class="col-12 col-sm-6 col-md-4">
        <q-input v-model="deviceFilter" dense outlined clearable debounce="200" label="Device groups">
          <template #prepend><q-icon name="search" /></template>
        </q-input>
      </div>
      <div class="col-12 col-sm-6 col-md-4">
        <q-input v-model="userFilter" dense outlined clearable debounce="200" label="User groups">
          <template #prepend><q-icon name="search" /></template>
        </q-input>
      </div>
    </div>

    <q-inner-loading :showing="loading" />
    <div v-if="!loading" class="matrix-scroll">
      <q-markup-table flat bordered dense separator="cell">
        <thead>
          <tr>
            <th class="text-left">Device group</th>
            <th
              v-for="group in shownUserGroups"
              :key="group.id"
              class="text-center"
              :class="{ 'global-admin': group.is_global_admin }"
            >
              {{ group.name }}
              <q-tooltip v-if="group.is_global_admin">Global administrators: every permission everywhere</q-tooltip>
            </th>
          </tr>
        </thead>
        <tbody>
          <tr v-for="deviceGroup in shownDeviceGroups" :key="deviceGroup.id">
            <td>{{ deviceGroup.name }}</td>
            <td
              v-for="group in shownUserGroups"
              :key="group.id"
              class="text-center cell"
              :class="{ 'global-admin': group.is_global_admin }"
            >
              {{ cell(group, deviceGroup.id) }}
            </td>
          </tr>
          <tr v-if="!shownDeviceGroups.length">
            <td :colspan="shownUserGroups.length + 1" class="text-muted">No device groups match</td>
          </tr>
        </tbody>
      </q-markup-table>
    </div>
  </PageCard>
</template>

<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'

import { deviceGroupsApi, userGroupsApi } from '@/api/endpoints'
import type { DeviceGroup, Id, UserGroup } from '@/api/types'
import PageCard from '@/components/PageCard.vue'
import { useNotify } from '@/composables/useNotify'
import { FLAGS, flagLetters, heldFlags } from '@/utils/grants'

const notify = useNotify()
const deviceGroups = ref<DeviceGroup[]>([])
const userGroups = ref<UserGroup[]>([])
const loading = ref(true)
const deviceFilter = ref<string | null>('')
const userFilter = ref<string | null>('')

const matches = (name: string, filter: string | null) => name.toLowerCase().includes((filter ?? '').trim().toLowerCase())
const shownDeviceGroups = computed(() => deviceGroups.value.filter((group) => matches(group.name, deviceFilter.value)))
const shownUserGroups = computed(() => userGroups.value.filter((group) => matches(group.name, userFilter.value)))

const ALL = flagLetters(FLAGS.map((info) => info.flag))

function cell(group: UserGroup, deviceGroup: Id): string {
  if (group.is_global_admin) return ALL
  const grant = group.grants.find((row) => row.device_group === deviceGroup)
  return grant ? flagLetters(heldFlags(grant)) : ''
}

onMounted(async () => {
  try {
    ;[deviceGroups.value, userGroups.value] = await Promise.all([deviceGroupsApi.list(), userGroupsApi.list()])
  } catch (error) {
    notify.error(error, 'Failed to load access')
  } finally {
    loading.value = false
  }
})
</script>

<style scoped>
.matrix-scroll {
  overflow-x: auto;
}

.cell {
  font-family: ui-monospace, SFMono-Regular, Menlo, Consolas, monospace;
  white-space: nowrap;
}

.global-admin {
  background: rgba(156, 39, 176, 0.12);
}
</style>
