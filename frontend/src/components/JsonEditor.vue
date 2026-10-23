<!-- SPDX-License-Identifier: GPL-3.0-or-later -->
<!--
  Edits a JSON object as text. The text is the source of truth while typing,
  so intermediate invalid input is kept (and flagged) rather than reverted;
  the model only updates when the text parses to an object.
-->
<template>
  <q-input
    :model-value="text"
    type="textarea"
    outlined
    autogrow
    :label="label"
    :hint="hint"
    :rules="[() => error || true]"
    input-class="json-input"
    @update:model-value="onInput"
  />
</template>

<script setup lang="ts">
import { ref, watch } from 'vue'

import type { JsonObject } from '@/api/types'

defineProps<{ label?: string; hint?: string }>()
const model = defineModel<JsonObject>({ required: true })

const pretty = (value: JsonObject) => JSON.stringify(value ?? {}, null, 2)

const text = ref(pretty(model.value))
const error = ref('')
// Compared by value: the parent usually stores what we emit in reactive state,
// so it comes back as a different (proxied) object.
let lastEmitted = JSON.stringify(model.value ?? {})

// Replace the text only when the model changes from outside (e.g. the dialog
// is reopened for another row), never in response to our own updates, which
// would reformat the text and move the cursor while typing.
watch(model, (value) => {
  if (JSON.stringify(value ?? {}) !== lastEmitted) {
    text.value = pretty(value)
    error.value = ''
    lastEmitted = JSON.stringify(value ?? {})
  }
})

function onInput(value: string | number | null): void {
  text.value = String(value ?? '')
  let parsed: unknown
  try {
    parsed = JSON.parse(text.value || '{}')
  } catch (exc) {
    error.value = `Invalid JSON: ${exc instanceof Error ? exc.message : String(exc)}`
    return
  }
  if (parsed === null || typeof parsed !== 'object' || Array.isArray(parsed)) {
    error.value = 'Must be a JSON object, e.g. {"key": "value"}'
    return
  }
  error.value = ''
  lastEmitted = JSON.stringify(parsed)
  model.value = parsed as JsonObject
}
</script>

<style scoped>
:deep(.json-input) {
  font-family: ui-monospace, SFMono-Regular, Menlo, Consolas, monospace;
  font-size: 0.85rem;
  min-height: 8em;
}
</style>
