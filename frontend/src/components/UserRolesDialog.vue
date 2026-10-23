<!-- SPDX-License-Identifier: GPL-3.0-or-later -->
<template>
  <q-dialog v-model="open" @before-show="load">
    <q-card style="width: 560px; max-width: 95vw">
      <q-card-section class="row items-center q-pb-none">
        <div class="text-h6">Device group roles · {{ user?.username }}</div>
        <q-space />
        <q-btn v-close-popup icon="close" flat round dense aria-label="Close" />
      </q-card-section>

      <q-card-section>
        <div class="text-subtitle2 q-mb-sm">Assigned</div>
        <q-inner-loading :showing="loading" />
        <q-list v-if="assignments.length" bordered separator>
          <q-item v-for="assignment in assignments" :key="assignment.id">
            <q-item-section>
              <q-item-label>{{ assignment.role.name }}</q-item-label>
              <q-item-label caption>{{ assignment.role.device_group_name }}</q-item-label>
            </q-item-section>
            <q-item-section side>
              <q-btn
                flat
                dense
                round
                color="negative"
                icon="delete"
                :aria-label="`Remove ${assignment.role.name}`"
                :disable="busy"
                @click="remove(assignment)"
              />
            </q-item-section>
          </q-item>
        </q-list>
        <div v-else-if="!loading" class="text-grey-6">No roles assigned</div>
      </q-card-section>

      <q-card-section>
        <div class="text-subtitle2 q-mb-sm">Add role</div>
        <div class="row q-col-gutter-sm items-center">
          <div class="col">
            <q-select
              v-model="selectedRole"
              :options="availableRoles"
              option-value="id"
              option-label="name"
              emit-value
              map-options
              outlined
              dense
              label="Role"
            >
              <template #option="scope">
                <q-item v-bind="scope.itemProps">
                  <q-item-section>
                    <q-item-label>{{ scope.opt.name }}</q-item-label>
                    <q-item-label caption>{{ scope.opt.device_group_name }}</q-item-label>
                  </q-item-section>
                </q-item>
              </template>
            </q-select>
          </div>
          <div class="col-auto">
            <q-btn color="primary" label="Assign" :disable="selectedRole === null" :loading="busy" @click="assign" />
          </div>
        </div>
      </q-card-section>
    </q-card>
  </q-dialog>
</template>

<script setup lang="ts">
import { computed, ref } from 'vue'

import { deviceGroupRolesApi, userRolesApi } from '@/api/endpoints'
import type { DeviceGroupRole, Id, User, UserRoleAssignment } from '@/api/types'
import { useNotify } from '@/composables/useNotify'

const props = defineProps<{ user: User | null }>()
const open = defineModel<boolean>({ required: true })

const notify = useNotify()
const roles = ref<DeviceGroupRole[]>([])
const assignments = ref<UserRoleAssignment[]>([])
const selectedRole = ref<Id | null>(null)
const loading = ref(false)
const busy = ref(false)

const availableRoles = computed(() => {
  const assigned = new Set(assignments.value.map((a) => a.role.id))
  return roles.value.filter((role) => !assigned.has(role.id))
})

async function loadAssignments(): Promise<void> {
  if (props.user) assignments.value = await userRolesApi.listForUser(props.user.id)
}

async function load(): Promise<void> {
  selectedRole.value = null
  assignments.value = []
  loading.value = true
  try {
    const [allRoles] = await Promise.all([deviceGroupRolesApi.list(), loadAssignments()])
    roles.value = allRoles
  } catch (error) {
    notify.error(error, 'Failed to load roles')
  } finally {
    loading.value = false
  }
}

async function assign(): Promise<void> {
  if (!props.user || selectedRole.value === null) return
  busy.value = true
  try {
    await userRolesApi.assign(props.user.id, selectedRole.value)
    selectedRole.value = null
    await loadAssignments()
    notify.success('Role assigned')
  } catch (error) {
    notify.error(error, 'Failed to assign role')
  } finally {
    busy.value = false
  }
}

async function remove(assignment: UserRoleAssignment): Promise<void> {
  busy.value = true
  try {
    await userRolesApi.remove(assignment.id)
    await loadAssignments()
    notify.success('Role removed')
  } catch (error) {
    notify.error(error, 'Failed to remove role')
  } finally {
    busy.value = false
  }
}
</script>
