<!-- SPDX-License-Identifier: GPL-3.0-or-later -->
<!-- A receiver's monitoring relay as it last reported it: URL, certificate, snapshots, request counts. -->
<template>
  <div class="text-caption q-mt-xs">
    <div>
      <span class="text-grey">Relay </span>
      <span class="mono">{{ relayUrl(host, relay.port) }}</span>
    </div>
    <div v-if="relay.certificate_fingerprint" class="text-grey">
      certificate <span class="mono short">{{ relay.certificate_fingerprint }}</span>
      <q-tooltip>TLS certificate SHA-256: {{ relay.certificate_fingerprint }}</q-tooltip>
    </div>
    <div :class="summary.stale || !summary.count ? 'text-warning' : 'text-grey'">
      <template v-if="summary.count">
        {{ summary.count }} snapshot{{ summary.count === 1 ? '' : 's' }}, oldest published
        {{ formatRelativeTime(summary.oldest) }}<template v-if="summary.stale"> (stale)</template>
      </template>
      <template v-else>No snapshot loaded: answers 503 stale</template>
    </div>
    <div class="text-grey">
      {{ relay.requests }} request{{ relay.requests === 1 ? '' : 's' }} · {{ relay.refused }} refused
      <template v-if="relay.throttled"> · {{ relay.throttled }} throttled</template>
    </div>
  </div>
</template>

<script setup lang="ts">
import { computed } from 'vue'

import type { RelayStatus } from '@/api/types'
import { formatRelativeTime } from '@/utils/datetime'
import { relayUrl, snapshotSummary } from '@/utils/relay'

const props = defineProps<{ relay: RelayStatus; host: string }>()

const summary = computed(() => snapshotSummary(props.relay))
</script>

<style scoped>
.mono {
  font-family: ui-monospace, SFMono-Regular, Menlo, Consolas, monospace;
  word-break: break-all;
}
.short {
  display: inline-block;
  max-width: 14em;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
  vertical-align: bottom;
}
</style>
