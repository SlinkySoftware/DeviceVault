<!-- SPDX-License-Identifier: GPL-3.0-or-later -->
<!-- Horizontal bars, one row per item, scaled to the largest. Labels and values are text, so nothing is colour-only. -->
<template>
  <ul class="bar-list" :aria-label="label">
    <li v-for="row in rows" :key="row.key" class="bar-list__row">
      <div class="bar-list__text">
        <span class="bar-list__label">
          <slot name="label" :row="row">{{ row.label }}</slot>
        </span>
        <span class="bar-list__value">{{ row.display }}</span>
      </div>
      <div v-if="row.caption" class="bar-list__caption text-muted">{{ row.caption }}</div>
      <div class="bar-list__track">
        <div class="bar-list__bar" :style="{ width: `${share(row.value)}%`, background: color }" />
      </div>
    </li>
    <li v-if="rows.length === 0" class="text-muted q-pa-sm">{{ emptyText }}</li>
  </ul>
</template>

<script setup lang="ts">
import { computed } from 'vue'

import type { BarRow } from './types'

const props = withDefaults(defineProps<{ rows: BarRow[]; label: string; color?: string; emptyText?: string }>(), {
  color: 'var(--chart-1)',
  emptyText: 'Nothing to show',
})

const largest = computed(() => Math.max(0, ...props.rows.map((row) => row.value)))
// A non-zero value always shows at least a sliver.
const share = (value: number) => (largest.value > 0 && value > 0 ? Math.max(1, (value / largest.value) * 100) : 0)
</script>

<style scoped>
.bar-list {
  list-style: none;
  margin: 0;
  padding: 0;
}

.bar-list__row + .bar-list__row {
  margin-top: 10px;
}

.bar-list__text {
  display: flex;
  justify-content: space-between;
  gap: 12px;
  font-size: 0.875rem;
}

.bar-list__label {
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.bar-list__value {
  font-weight: 600;
  font-variant-numeric: tabular-nums;
  white-space: nowrap;
}

.bar-list__caption {
  font-size: 0.75rem;
}

.bar-list__track {
  margin-top: 4px;
  height: 10px;
}

.bar-list__bar {
  height: 100%;
  border-radius: 0 4px 4px 0;
}
</style>
