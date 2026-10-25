<!-- SPDX-License-Identifier: GPL-3.0-or-later -->
<!-- A dashboard card. While reloading it dims what it shows; on failure it says so and offers a retry. -->
<template>
  <q-card class="dashboard-card column no-wrap">
    <q-card-section class="dashboard-card__title row items-center q-py-sm">
      <div class="col">
        <div class="text-h6 text-weight-bold">{{ title }}</div>
        <div v-if="caption" class="text-caption text-muted">{{ caption }}</div>
      </div>
      <slot name="actions" />
    </q-card-section>
    <q-separator />
    <q-card-section class="col q-pa-sm dashboard-card__body" :class="{ 'dashboard-card__body--loading': loading }">
      <div v-if="failed" class="row items-center q-gutter-sm q-pa-sm text-negative">
        <q-icon name="error_outline" />
        <span>Could not load this card.</span>
        <q-btn flat dense no-caps color="primary" label="Retry" @click="emit('retry')" />
      </div>
      <slot />
    </q-card-section>
  </q-card>
</template>

<script setup lang="ts">
withDefaults(defineProps<{ title: string; caption?: string; loading?: boolean; failed?: boolean }>(), {
  loading: false,
  failed: false,
})
const emit = defineEmits<{ retry: [] }>()
</script>

<style scoped>
.dashboard-card {
  height: 100%;
}

.dashboard-card__title {
  background: #f5f5f5;
  border-bottom: var(--accent-border);
}

body.body--dark .dashboard-card__title {
  background: rgba(255, 255, 255, 0.04);
}

.dashboard-card__body {
  transition: opacity 0.2s;
}

.dashboard-card__body--loading {
  opacity: 0.55;
}
</style>
