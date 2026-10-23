<!-- SPDX-License-Identifier: GPL-3.0-or-later -->
<template>
  <template v-if="value">
    <div>{{ formatDateTimeShort(value) }}</div>
    <div class="text-caption text-grey">{{ formatRelativeTime(value) }}</div>
  </template>
  <span v-else class="text-grey">—</span>
</template>

<script setup lang="ts">
import { formatDateTimeShort, formatRelativeTime } from '@/utils/datetime'

defineProps<{ value: string | null }>()
</script>
