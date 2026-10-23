<!-- SPDX-License-Identifier: GPL-3.0-or-later -->
<template>
  <div class="stat-box column no-wrap items-center justify-center" :class="{ 'stat-box--large': large }">
    <q-icon v-if="icon" :name="icon" color="primary" size="md" />
    <div class="text-subtitle2 text-weight-medium">{{ label }}</div>
    <div class="stat-box__value text-weight-bold" :class="`text-${color}`">{{ value }}</div>
  </div>
</template>

<script setup lang="ts">
withDefaults(defineProps<{ label: string; value: string | number; color?: string; large?: boolean; icon?: string }>(), {
  color: 'primary',
  large: false,
})
</script>

<style scoped>
.stat-box {
  border: var(--nested-border);
  background: var(--nested-bg);
  border-radius: 8px;
  padding: 10px 12px;
  flex: 1 1 0;
  min-height: 72px;
  text-align: center;
}

.stat-box__value {
  font-size: clamp(1.25rem, 3vw, 2.25rem);
  line-height: 1.1;
}

.stat-box--large .stat-box__value {
  font-size: clamp(2rem, 5vw, 4rem);
}
</style>
