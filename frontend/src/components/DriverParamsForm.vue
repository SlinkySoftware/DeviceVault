<!-- SPDX-License-Identifier: GPL-3.0-or-later -->
<!--
  Per-device settings for a collector driver, built from the parameter schema
  the driver publishes. Empty fields are left out, so the driver's defaults
  apply. Properties the form cannot render fall back to a JSON editor.
-->
<template>
  <div v-if="fields.length || unsupported.length" class="column q-gutter-y-md">
    <div class="text-subtitle2">{{ title }}</div>
    <template v-for="field in fields" :key="field.name">
      <q-toggle
        v-if="field.kind === 'boolean'"
        :model-value="Boolean(value(field))"
        :label="field.label"
        :disable="disable"
        @update:model-value="set(field, $event)"
      >
        <q-tooltip v-if="field.description">{{ field.description }}</q-tooltip>
      </q-toggle>
      <q-select
        v-else-if="field.kind === 'enum'"
        :model-value="value(field)"
        :options="field.options"
        :label="field.label"
        :hint="field.description || undefined"
        :clearable="!field.required"
        :disable="disable"
        outlined
        @update:model-value="set(field, $event)"
      />
      <q-select
        v-else-if="field.kind === 'list'"
        :model-value="listValue(field)"
        :label="field.label"
        :hint="field.description || 'Type a value and press Enter'"
        :disable="disable"
        multiple
        use-chips
        use-input
        hide-dropdown-icon
        new-value-mode="add-unique"
        outlined
        @update:model-value="set(field, $event?.length ? $event : undefined)"
      />
      <q-input
        v-else
        :model-value="inputValue(field)"
        :type="field.kind === 'string' ? 'text' : 'number'"
        :label="field.label"
        :hint="hint(field)"
        :rules="[(v) => checkField(field, parse(field, v))]"
        :disable="disable"
        outlined
        @update:model-value="set(field, parse(field, $event))"
      />
    </template>
    <JsonEditor
      v-if="unsupported.length"
      :model-value="extra"
      label="Other parameters (JSON)"
      :hint="`Settings the form cannot show: ${unsupported.join(', ')}`"
      @update:model-value="setExtra"
    />
  </div>
</template>

<script setup lang="ts">
import { computed } from 'vue'

import type { JsonObject } from '@/api/types'
import JsonEditor from '@/components/JsonEditor.vue'
import { checkField, schemaFields, type JsonSchema, type SchemaField } from '@/utils/schema'

const props = withDefaults(defineProps<{ schema: JsonSchema | null | undefined; title?: string; disable?: boolean }>(), {
  title: 'Driver settings',
  disable: false,
})
const model = defineModel<JsonObject>({ required: true })

const parsed = computed(() => schemaFields(props.schema))
const fields = computed(() => parsed.value.fields)
const unsupported = computed(() => parsed.value.unsupported)

/** The stored value, or the default the driver will use. */
const value = (field: SchemaField) => model.value[field.name] ?? field.default

const inputValue = (field: SchemaField) => model.value[field.name] as string | number | null | undefined
const listValue = (field: SchemaField) => (value(field) as string[] | undefined) ?? []

const hint = (field: SchemaField) => {
  const fallback = field.default === undefined || field.default === null ? '' : `Default: ${String(field.default)}`
  return [field.description, fallback].filter(Boolean).join('. ') || undefined
}

function parse(field: SchemaField, input: string | number | null): unknown {
  if (input === null || input === '') return undefined
  if (field.kind === 'integer' || field.kind === 'number') {
    const number = Number(input)
    return Number.isNaN(number) ? input : number
  }
  return input
}

function set(field: SchemaField, next: unknown): void {
  const updated = { ...model.value }
  if (next === undefined || next === null) delete updated[field.name]
  else updated[field.name] = next
  model.value = updated
}

const extra = computed<JsonObject>(() =>
  Object.fromEntries(Object.entries(model.value).filter(([name]) => unsupported.value.includes(name))),
)

function setExtra(next: JsonObject): void {
  const known = Object.fromEntries(Object.entries(model.value).filter(([name]) => !unsupported.value.includes(name)))
  model.value = { ...known, ...next }
}
</script>
