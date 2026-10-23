<!-- SPDX-License-Identifier: GPL-3.0-or-later -->
<!--
  Side-by-side diff. Both sides share one virtualised grid, so they can never
  scroll out of step and only visible rows are rendered (configurations can
  be tens of MB). Text is rendered as text, never as HTML.
-->
<template>
  <div class="diff-view">
    <div class="row items-center q-gutter-sm q-mb-sm">
      <q-badge color="positive" outline>+{{ summary.added }} added</q-badge>
      <q-badge color="negative" outline>-{{ summary.removed }} removed</q-badge>
      <q-badge color="warning" outline>~{{ summary.modified }} modified</q-badge>
      <q-space />
      <q-toggle v-model="changesOnly" dense label="Changes only" :disable="identical" />
    </div>

    <div class="diff-header">
      <div class="diff-title diff-title--a">
        <slot name="left-title">{{ leftTitle }}</slot>
      </div>
      <div class="diff-title diff-title--b">
        <slot name="right-title">{{ rightTitle }}</slot>
      </div>
    </div>

    <div v-if="identical" class="text-center text-grey q-pa-lg">The backups are identical.</div>
    <q-virtual-scroll v-else v-slot="{ item }" :items="visibleRows" class="diff-body" :virtual-scroll-item-size="22">
      <div :key="item.index" class="diff-row" :class="`diff-row--${item.row.kind}`">
        <span class="diff-num">{{ item.row.leftNumber ?? '' }}</span>
        <span class="diff-cell diff-cell--left">
          <template v-if="item.row.leftSegments">
            <span v-for="(seg, i) in item.row.leftSegments" :key="i" :class="{ 'diff-change': seg.changed }">{{
              seg.text
            }}</span>
          </template>
          <template v-else>{{ item.row.left ?? '' }}</template>
        </span>
        <span class="diff-num">{{ item.row.rightNumber ?? '' }}</span>
        <span class="diff-cell diff-cell--right">
          <template v-if="item.row.rightSegments">
            <span v-for="(seg, i) in item.row.rightSegments" :key="i" :class="{ 'diff-change': seg.changed }">{{
              seg.text
            }}</span>
          </template>
          <template v-else>{{ item.row.right ?? '' }}</template>
        </span>
      </div>
    </q-virtual-scroll>
  </div>
</template>

<script setup lang="ts">
import { computed, ref } from 'vue'

import { sideBySideDiff, summarise } from '@/utils/diff'

const props = defineProps<{ left: string; right: string; leftTitle?: string; rightTitle?: string }>()

const changesOnly = ref(false)
const rows = computed(() => sideBySideDiff(props.left, props.right))
const summary = computed(() => summarise(rows.value))
const identical = computed(() => summary.value.added + summary.value.removed + summary.value.modified === 0)
const visibleRows = computed(() =>
  rows.value
    .map((row, index) => ({ row, index }))
    .filter(({ row }) => !changesOnly.value || row.kind !== 'equal'),
)
</script>

<style scoped>
.diff-header,
.diff-row {
  display: grid;
  grid-template-columns: 4em 1fr 4em 1fr;
}

.diff-title {
  grid-column: span 2;
  padding: 8px 12px;
  color: #fff;
  font-weight: 600;
}

.diff-title--a {
  background: #12314f;
}

.diff-title--b {
  background: #1f4a2e;
}

.diff-body {
  max-height: 70vh;
  background: #1e1e1e;
  color: #e0e0e0;
  border: 1px solid #2d2d2d;
  font-family: ui-monospace, SFMono-Regular, Menlo, Consolas, monospace;
  font-size: 12px;
  line-height: 1.5;
}

.diff-row {
  min-height: 22px;
}

.diff-num {
  padding: 0 8px;
  text-align: right;
  color: #6e7681;
  user-select: none;
}

.diff-cell {
  padding: 0 8px;
  white-space: pre-wrap;
  word-break: break-all;
}

.diff-row--added .diff-cell--right,
.diff-row--added .diff-cell--left {
  background: rgba(46, 160, 67, 0.25);
}

.diff-row--removed .diff-cell--left,
.diff-row--removed .diff-cell--right {
  background: rgba(248, 81, 73, 0.25);
}

.diff-row--modified .diff-cell {
  background: rgba(187, 128, 9, 0.22);
}

.diff-change {
  background: #ffeb3b;
  color: #222;
  font-weight: 700;
}
</style>
