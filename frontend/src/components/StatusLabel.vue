<!-- SPDX-License-Identifier: GPL-3.0-or-later -->
<template>
  <span class="row inline items-center no-wrap">
    <q-icon :name="statusIcon(status)" :color="statusColor(status)" size="sm" :class="{ pulse: pending }" />
    <span class="q-ml-xs">{{ label || statusLabel(status) }}</span>
  </span>
</template>

<script setup lang="ts">
import { computed } from 'vue'

import { isActiveJob, statusColor, statusIcon, statusLabel } from '@/utils/format'

const props = defineProps<{ status: string | null; label?: string }>()
const pending = computed(() => isActiveJob(props.status))
</script>

<style scoped>
@keyframes pulse {
  50% {
    transform: scale(1.15);
    opacity: 0.7;
  }
}

.pulse {
  animation: pulse 1.2s ease-in-out infinite;
}
</style>
