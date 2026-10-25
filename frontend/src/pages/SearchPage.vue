<!-- SPDX-License-Identifier: GPL-3.0-or-later -->
<template>
  <PageCard title="Config Search" caption="The latest backup of every device whose backups you may read">
    <q-form class="row q-col-gutter-sm items-start" @submit.prevent="submit">
      <div class="col-12 col-md">
        <q-input
          v-model="form.q"
          outlined
          dense
          autofocus
          clearable
          :label="form.mode === 'regex' ? 'Regular expression (RE2, per line)' : 'Text (a line typed with its secret in it matches)'"
          input-class="search-input"
          :maxlength="256"
        >
          <template #prepend><q-icon name="search" /></template>
        </q-input>
      </div>
      <div class="col-auto">
        <q-btn-toggle
          v-model="form.mode"
          no-caps
          unelevated
          toggle-color="primary"
          :options="[
            { label: 'Text', value: 'text' },
            { label: 'Regex', value: 'regex' },
          ]"
        />
      </div>
      <div class="col-12 col-sm-6 col-md-2">
        <q-select
          v-model="form.device_group"
          outlined
          dense
          clearable
          emit-value
          map-options
          label="Device group"
          :options="groupOptions"
        />
      </div>
      <div class="col-12 col-sm-6 col-md-2">
        <q-select
          v-model="form.driver"
          outlined
          dense
          clearable
          emit-value
          map-options
          label="Backup method"
          :options="driverOptions"
        />
      </div>
      <div class="col-auto">
        <q-btn type="submit" color="primary" icon="search" label="Search" :loading="loading" :disable="!form.q" />
      </div>
    </q-form>

    <div v-if="reply" class="q-mt-md">
      <div class="text-subtitle2 q-mb-sm">
        {{ summary }}
      </div>
      <q-banner v-if="reply.truncated" dense class="bg-warning text-dark q-mb-sm" rounded>
        Only the first {{ reply.results.length }} devices are shown; make the search more specific or filter it.
      </q-banner>
      <q-banner v-if="reply.timed_out" dense class="bg-warning text-dark q-mb-sm" rounded>
        The search stopped before looking at every device; make it more specific or filter it.
      </q-banner>

      <q-card v-for="result in reply.results" :key="result.device" flat bordered class="q-mb-sm">
        <q-card-section class="q-py-sm row items-center q-gutter-x-sm">
          <router-link :to="{ name: 'device-backups', params: { id: result.device } }" class="text-weight-medium device-link">
            {{ result.device_name }}
          </router-link>
          <q-badge v-if="result.device_group_name" outline color="primary">{{ result.device_group_name }}</q-badge>
          <span class="text-caption text-grey">
            {{ result.match_count }} {{ result.match_count === 1 ? 'line' : 'lines' }} · backup of
            {{ formatDateTime(result.backup_at) }}
          </span>
        </q-card-section>
        <q-separator />
        <div class="lines">
          <router-link
            v-for="line in result.lines"
            :key="line.number"
            :to="lineTarget(result, line.number)"
            class="line"
          >
            <span class="number">{{ line.number }}</span>
            <span class="text">
              <template v-for="(segment, index) in splitSecretTokens(line.text)" :key="index">
                <span v-if="segment.secret" class="secret">
                  <q-icon name="key" size="xs" /> secret
                  <q-tooltip>A secret value; open the backup to see it</q-tooltip>
                </span>
                <template v-else>{{ segment.text }}</template>
              </template>
            </span>
          </router-link>
          <div v-if="result.match_count > result.lines.length" class="text-caption text-grey q-px-md q-py-xs">
            and {{ result.match_count - result.lines.length }} more
          </div>
        </div>
      </q-card>
    </div>
  </PageCard>
</template>

<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'
import type { RouteLocationRaw } from 'vue-router'

import { backupMethodsApi, deviceGroupsApi, searchApi } from '@/api/endpoints'
import type { BackupMethod, DeviceGroup, SearchQuery, SearchResult } from '@/api/types'
import PageCard from '@/components/PageCard.vue'
import { useNotify } from '@/composables/useNotify'
import { useSearchStore } from '@/stores/search'
import { formatDateTime } from '@/utils/datetime'
import { splitSecretTokens } from '@/utils/search'

const notify = useNotify()
// The last search lives in memory, not the URL: a query may hold a secret.
const store = useSearchStore()
const form = store.form
const reply = computed(() => store.reply)

const loading = ref(false)
const groups = ref<DeviceGroup[]>([])
const methods = ref<BackupMethod[]>([])

const groupOptions = computed(() => groups.value.map((group) => ({ label: group.name, value: group.id })))
const driverOptions = computed(() => methods.value.map((method) => ({ label: method.friendly_name, value: method.key })))

const summary = computed(() => {
  if (!reply.value) return ''
  const matched = reply.value.results.length
  const searched = reply.value.searched_devices
  return `${matched} of ${searched} ${searched === 1 ? 'device' : 'devices'} matched`
})

const lineTarget = (result: SearchResult, line: number): RouteLocationRaw => ({
  name: 'device-backups',
  params: { id: result.device },
  query: { view: result.job, line },
})

async function submit(): Promise<void> {
  if (!form.q) return
  const query: SearchQuery = { q: form.q, mode: form.mode }
  if (form.device_group !== null) query.device_group = form.device_group
  if (form.driver) query.driver = form.driver
  loading.value = true
  try {
    store.reply = await searchApi.search(query)
  } catch (error) {
    store.reply = null
    notify.error(error, 'Search failed')
  } finally {
    loading.value = false
  }
}

onMounted(async () => {
  try {
    ;[groups.value, methods.value] = await Promise.all([deviceGroupsApi.list(), backupMethodsApi.list()])
  } catch (error) {
    notify.error(error, 'Failed to load the search filters')
  }
})
</script>

<style scoped>
.device-link {
  text-decoration: none;
}

.lines {
  font-family: ui-monospace, SFMono-Regular, Menlo, Consolas, monospace;
  font-size: 12px;
  line-height: 1.6;
}

.line {
  display: flex;
  color: inherit;
  text-decoration: none;
}

.line:hover {
  background: rgba(127, 127, 127, 0.12);
}

.number {
  flex: 0 0 4.5em;
  padding-right: 1em;
  text-align: right;
  color: #888;
  user-select: none;
}

.text {
  white-space: pre-wrap;
  word-break: break-word;
}

.secret {
  display: inline-flex;
  align-items: center;
  gap: 2px;
  padding: 0 6px;
  border-radius: 8px;
  background: rgba(127, 127, 127, 0.2);
  font-family: inherit;
}

:deep(.search-input) {
  font-family: ui-monospace, SFMono-Regular, Menlo, Consolas, monospace;
}
</style>
