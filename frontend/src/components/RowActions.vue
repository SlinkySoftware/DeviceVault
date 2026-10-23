<!-- SPDX-License-Identifier: GPL-3.0-or-later -->
<template>
  <div class="row no-wrap justify-end q-gutter-xs">
    <slot />
    <q-btn dense color="primary" icon="edit" label="Edit" :disable="editDisabled" @click="emit('edit')">
      <q-tooltip v-if="editDisabled && editDisabledReason">{{ editDisabledReason }}</q-tooltip>
    </q-btn>
    <q-btn dense color="negative" icon="delete" label="Delete" :disable="deleteDisabled" @click="emit('delete')">
      <q-tooltip v-if="deleteDisabled && deleteDisabledReason">{{ deleteDisabledReason }}</q-tooltip>
    </q-btn>
  </div>
</template>

<script setup lang="ts">
defineProps<{
  editDisabled?: boolean
  editDisabledReason?: string
  deleteDisabled?: boolean
  deleteDisabledReason?: string
}>()
const emit = defineEmits<{ edit: []; delete: [] }>()
</script>
