<!-- SPDX-License-Identifier: GPL-3.0-or-later -->
<!-- Dialog wrapping a validated q-form; emits `submit` only when every rule passes. -->
<template>
  <q-dialog v-model="open">
    <q-card :style="{ width, maxWidth: '95vw' }">
      <q-form greedy @submit="emit('submit')">
        <q-card-section class="row items-center q-pb-none">
          <div class="text-h6">{{ title }}</div>
          <q-space />
          <q-btn v-close-popup icon="close" flat round dense aria-label="Close" />
        </q-card-section>
        <q-card-section class="q-gutter-md">
          <slot />
        </q-card-section>
        <q-card-actions align="right">
          <q-btn v-close-popup flat :label="readonly ? 'Close' : 'Cancel'" />
          <q-btn v-if="!readonly" color="primary" type="submit" :label="submitLabel" :loading="saving" />
        </q-card-actions>
      </q-form>
    </q-card>
  </q-dialog>
</template>

<script setup lang="ts">
withDefaults(
  defineProps<{
    title: string
    saving?: boolean
    readonly?: boolean
    submitLabel?: string
    width?: string
  }>(),
  { saving: false, readonly: false, submitLabel: 'Save', width: '520px' },
)

const open = defineModel<boolean>({ required: true })
const emit = defineEmits<{ submit: [] }>()
</script>
