<!-- SPDX-License-Identifier: GPL-3.0-or-later -->
<template>
  <PageCard title="Flower" caption="Celery monitoring dashboards for the workers and queues">
    <template #actions>
      <q-btn color="primary" icon="add" label="Add Flower Endpoint" @click="crud.openCreate" />
    </template>

    <q-table flat :rows="crud.rows.value" :columns="columns" row-key="id" :loading="crud.loading.value" class="admin-table">
      <template #body-cell-link="props">
        <q-td :props="props"><code>{{ props.row.link }}</code></q-td>
      </template>
      <template #body-cell-proxied="props">
        <q-td :props="props">
          <q-badge :color="props.row.proxied ? 'positive' : 'grey'" :label="props.row.proxied ? 'Proxied' : 'Direct'" />
          <q-tooltip>
            {{ props.row.proxied ? `The web tier serves it to administrators, from ${props.row.url}` : 'Opened directly; it must secure itself' }}
          </q-tooltip>
        </q-td>
      </template>
      <template #body-cell-actions="props">
        <q-td :props="props">
          <q-btn
            flat
            dense
            color="primary"
            icon="open_in_new"
            label="Open"
            :href="props.row.link"
            target="_blank"
            :disable="props.row.proxied && !sessions.has(props.row.id)"
          />
          <RowActions @edit="crud.openEdit(props.row)" @delete="crud.confirmRemove(props.row)" />
        </q-td>
      </template>
    </q-table>

    <FormDialog
      v-model="crud.dialogOpen.value"
      :title="crud.isEditing.value ? 'Edit Flower Endpoint' : 'Add Flower Endpoint'"
      :saving="crud.saving.value"
      @submit="crud.save"
    >
      <q-input v-model.trim="crud.form.value.name" label="Name" outlined autofocus :rules="[required]" />
      <q-toggle v-model="crud.form.value.proxied" label="Proxy through DeviceVault" />
      <q-input
        v-model.trim="crud.form.value.slug"
        label="Slug"
        outlined
        :hint="
          crud.form.value.proxied
            ? `Served at /flower/${crud.form.value.slug || '<slug>'}/; run Flower with --url_prefix=flower/${crud.form.value.slug || '<slug>'}`
            : 'A short unique identifier'
        "
        :rules="[required, slug]"
      />
      <q-input
        v-model.trim="crud.form.value.url"
        label="URL"
        outlined
        :hint="
          crud.form.value.proxied
            ? 'Where the web tier reaches Flower, e.g. http://flower:5555'
            : 'Opened in a new tab; that Flower must require its own login'
        "
        :rules="[required]"
      />
    </FormDialog>
  </PageCard>
</template>

<script setup lang="ts">
import type { QTableColumn } from 'quasar'
import { reactive, watch } from 'vue'

import { flowerEndpointsApi } from '@/api/endpoints'
import type { FlowerEndpoint, FlowerEndpointWrite, Id } from '@/api/types'
import FormDialog from '@/components/FormDialog.vue'
import PageCard from '@/components/PageCard.vue'
import RowActions from '@/components/RowActions.vue'
import { useCrud } from '@/composables/useCrud'
import { required } from '@/utils/rules'

const slug = (value: string) => /^[a-z0-9-]+$/.test(value) || 'Lower-case letters, digits and "-" only'

const crud = useCrud<FlowerEndpoint, FlowerEndpointWrite>({
  api: flowerEndpointsApi,
  noun: 'Flower endpoint',
  emptyForm: () => ({ name: '', slug: '', url: '', proxied: true }),
  toForm: (row) => ({ name: row.name, slug: row.slug, url: row.url, proxied: row.proxied }),
})

// A new tab carries no API token, so each proxied endpoint gets a session
// cookie (scoped to its path) whenever the list loads.
const sessions = reactive(new Set<Id>())
watch(crud.rows, async (rows) => {
  sessions.clear()
  await Promise.all(
    rows
      .filter((row) => row.proxied)
      .map(async (row) => {
        try {
          await flowerEndpointsApi.session(row.id)
          sessions.add(row.id)
        } catch {
          // Open stays disabled; the endpoint may have just been deleted.
        }
      }),
  )
})

const columns: QTableColumn<FlowerEndpoint>[] = [
  { name: 'name', label: 'Name', field: 'name', align: 'left', sortable: true },
  { name: 'link', label: 'Address', field: 'link', align: 'left' },
  { name: 'proxied', label: 'Access', field: 'proxied', align: 'center' },
  { name: 'actions', label: 'Actions', field: 'id', align: 'right' },
]
</script>
