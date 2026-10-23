<!-- SPDX-License-Identifier: GPL-3.0-or-later -->
<template>
  <q-card class="dashboard-card column no-wrap">
    <q-card-section class="dashboard-card__title row items-center q-py-sm">
      <div class="text-h6 text-weight-bold col">{{ title }}</div>
      <slot name="actions" />
    </q-card-section>
    <q-separator />
    <q-card-section class="col q-pa-sm">
      <slot />
    </q-card-section>
  </q-card>
</template>

<script setup lang="ts">
defineProps<{ title: string }>()
</script>

<style scoped>
.dashboard-card {
  height: 100%;
}

.dashboard-card__title {
  background: #f5f5f5;
  border-bottom: 2px solid var(--theme-dashboard-box);
}

body.body--dark .dashboard-card__title {
  background: #1f1f1f;
}
</style>
