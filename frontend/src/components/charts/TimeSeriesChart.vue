<!-- SPDX-License-Identifier: GPL-3.0-or-later -->
<!--
  Daily series drawn as SVG: lines, or stacked columns. One axis, hairline grid, a legend
  for two or more series, a crosshair tooltip on hover and keyboard focus (arrow keys), and
  a visually hidden table holding every value.
-->
<template>
  <div class="ts-chart" :class="{ 'ts-chart--empty': empty }">
    <div v-if="series.length > 1" class="ts-chart__legend">
      <span v-for="s in series" :key="s.key" class="ts-chart__legend-item">
        <span class="ts-chart__key" :class="`ts-chart__key--${kind}`" :style="{ background: s.color }" />
        {{ s.label }}
      </span>
    </div>
    <div ref="box" class="ts-chart__plot" :style="{ height: `${height}px` }">
      <svg
        v-if="width > 0"
        :width="width"
        :height="height"
        role="img"
        :aria-label="label"
        tabindex="0"
        @pointerleave="active = null"
        @keydown="onKey"
        @blur="active = null"
      >
        <g class="ts-chart__grid">
          <template v-for="tick in ticks" :key="tick">
            <line :x1="PAD.left" :x2="width - PAD.right" :y1="y(tick)" :y2="y(tick)" :class="{ baseline: tick === 0 }" />
            <text :x="PAD.left - 8" :y="y(tick) + 4" text-anchor="end">{{ tickLabel(tick) }}</text>
          </template>
        </g>
        <g class="ts-chart__days">
          <template v-for="(day, i) in dates" :key="day">
            <text v-if="i % every === 0" :x="x(i)" :y="height - PAD.bottom + 16" text-anchor="middle">
              {{ dayLabel(day).top }}
            </text>
            <text v-if="i % every === 0 && dayLabel(day).bottom" :x="x(i)" :y="height - PAD.bottom + 30" text-anchor="middle">
              {{ dayLabel(day).bottom }}
            </text>
          </template>
        </g>

        <line
          v-if="active !== null"
          class="ts-chart__crosshair"
          :x1="x(active)"
          :x2="x(active)"
          :y1="PAD.top"
          :y2="height - PAD.bottom"
        />

        <g v-if="kind === 'bar'">
          <template v-for="(_, i) in dates" :key="i">
            <path
              v-for="segment in stack(i)"
              :key="segment.key"
              :d="segment.d"
              :fill="segment.color"
              :class="{ dim: active !== null && active !== i }"
            />
          </template>
        </g>
        <g v-else>
          <path v-for="s in series" :key="s.key" :d="linePath(s.values)" :stroke="s.color" class="ts-chart__line" />
          <template v-for="s in series" :key="`${s.key}-dots`">
            <template v-for="(value, i) in s.values" :key="i">
              <circle
                v-if="value !== null && (active === i || isolated(s.values, i))"
                :cx="x(i)"
                :cy="y(value)"
                r="4"
                :fill="s.color"
                class="ts-chart__dot"
              />
            </template>
          </template>
        </g>

        <rect
          v-for="(_, i) in dates"
          :key="`hit-${i}`"
          :x="x(i) - band / 2"
          :y="PAD.top"
          :width="band"
          :height="plotHeight"
          class="ts-chart__hit"
          @pointerenter="active = i"
        />
      </svg>
      <div v-if="empty" class="ts-chart__empty text-muted">{{ emptyText }}</div>
      <div
        v-if="active !== null && !empty"
        class="ts-chart__tooltip"
        :style="tooltipStyle"
        role="status"
        aria-live="polite"
      >
        <div class="ts-chart__tooltip-date">{{ fullDate(dates[active]!) }}</div>
        <div v-for="s in series" :key="s.key" class="ts-chart__tooltip-row">
          <span class="ts-chart__tooltip-key" :style="{ background: s.color }" />
          <strong>{{ valueLabel(s.values[active] ?? null) }}</strong>
          <span class="text-muted">{{ s.label }}</span>
        </div>
      </div>
    </div>
    <table class="visually-hidden">
      <caption>{{ label }}</caption>
      <thead>
        <tr>
          <th scope="col">Date</th>
          <th v-for="s in series" :key="s.key" scope="col">{{ s.label }}</th>
        </tr>
      </thead>
      <tbody>
        <tr v-for="(day, i) in dates" :key="day">
          <th scope="row">{{ fullDate(day) }}</th>
          <td v-for="s in series" :key="s.key">{{ valueLabel(s.values[i] ?? null) }}</td>
        </tr>
      </tbody>
    </table>
  </div>
</template>

<script setup lang="ts">
import { computed, onBeforeUnmount, onMounted, ref } from 'vue'

import { calendarDayLabel } from '@/utils/datetime'

import { compactNumber, labelEvery, niceTicks } from './scale'
import type { ChartSeries } from './types'

const props = withDefaults(
  defineProps<{
    /** Calendar days, `YYYY-MM-DD`, oldest first. */
    dates: string[]
    series: ChartSeries[]
    kind?: 'line' | 'bar'
    /** Accessible name; also the hidden table's caption. */
    label: string
    /** A fixed top of the axis (100 for percentages); otherwise it fits the data. */
    max?: number
    /** The values are counts: whole-number ticks only. */
    integer?: boolean
    format?: (value: number) => string
    height?: number
    emptyText?: string
  }>(),
  { kind: 'line', integer: false, height: 220, emptyText: 'No backups in this period' },
)

const PAD = { left: 44, right: 12, top: 12, bottom: 40 }
const BAR_MAX = 24
const GAP = 2
const RADIUS = 4

const box = ref<HTMLDivElement | null>(null)
const width = ref(0)
const active = ref<number | null>(null)
let observer: ResizeObserver | null = null

const plotWidth = computed(() => Math.max(0, width.value - PAD.left - PAD.right))
const plotHeight = computed(() => Math.max(0, props.height - PAD.top - PAD.bottom))
const band = computed(() => (props.dates.length ? plotWidth.value / props.dates.length : 0))

const values = computed(() => props.series.flatMap((s) => s.values.filter((v): v is number => v !== null)))
const empty = computed(() => values.value.every((v) => v === 0))
const dataMax = computed(() => {
  if (props.kind === 'line') return Math.max(0, ...values.value)
  return Math.max(0, ...props.dates.map((_, i) => props.series.reduce((sum, s) => sum + (s.values[i] ?? 0), 0)))
})
const ticks = computed(() =>
  props.max !== undefined ? niceTicks(props.max, 4, true) : niceTicks(dataMax.value, 4, false, props.integer),
)
const top = computed(() => ticks.value[ticks.value.length - 1] || 1)
const every = computed(() => labelEvery(props.dates.length, plotWidth.value, props.dates.length > 14 ? 44 : 36))

const x = (i: number) => PAD.left + band.value * (i + 0.5)
const y = (value: number) => PAD.top + plotHeight.value * (1 - value / top.value)

const valueLabel = (value: number | null) => (value === null ? '—' : props.format ? props.format(value) : compactNumber(value))
const tickLabel = (value: number) => (props.format ? props.format(value) : compactNumber(value))

function dayLabel(iso: string): { top: string; bottom: string } {
  const label = calendarDayLabel(iso)
  // Weekday over day number for a week or two; "3 Oct" when there are more.
  return props.dates.length > 14 ? { top: `${label.day} ${label.month}`, bottom: '' } : { top: label.weekday, bottom: String(label.day) }
}

function fullDate(iso: string): string {
  const label = calendarDayLabel(iso)
  return `${label.weekday} ${label.day} ${label.month}`
}

/** A point drawn as a dot because no line reaches it. */
function isolated(series: (number | null)[], i: number): boolean {
  return (series[i - 1] ?? null) === null && (series[i + 1] ?? null) === null
}

function linePath(series: (number | null)[]): string {
  let d = ''
  let drawing = false
  series.forEach((value, i) => {
    if (value === null) {
      drawing = false
      return
    }
    d += `${drawing ? 'L' : 'M'}${x(i).toFixed(1)},${y(value).toFixed(1)}`
    drawing = true
  })
  return d
}

/** A column from `y0` up to `y1`, its top corners rounded when it ends the stack. */
function column(cx: number, w: number, y0: number, y1: number, rounded: boolean): string {
  const left = cx - w / 2
  const r = rounded ? Math.min(RADIUS, w / 2, y0 - y1) : 0
  return (
    `M${left},${y0}V${y1 + r}` +
    (r ? `Q${left},${y1} ${left + r},${y1}H${left + w - r}Q${left + w},${y1} ${left + w},${y1 + r}` : `H${left + w}`) +
    `V${y0}Z`
  )
}

function stack(i: number): { key: string; d: string; color: string }[] {
  const w = Math.min(BAR_MAX, band.value * 0.7)
  const parts = props.series.map((s) => ({ s, value: s.values[i] ?? 0 })).filter((p) => p.value > 0)
  let base = 0
  return parts.map(({ s, value }, index) => {
    const y0 = y(base) - (index > 0 ? GAP / 2 : 0)
    base += value
    const y1 = y(base) + (index < parts.length - 1 ? GAP / 2 : 0)
    return { key: s.key, d: column(x(i), w, y0, Math.min(y1, y0 - 1), index === parts.length - 1), color: s.color }
  })
}

const tooltipStyle = computed(() => {
  if (active.value === null) return {}
  const left = x(active.value)
  const flip = left > width.value / 2
  return flip ? { right: `${width.value - left + 12}px`, top: `${PAD.top}px` } : { left: `${left + 12}px`, top: `${PAD.top}px` }
})

function onKey(event: KeyboardEvent): void {
  const last = props.dates.length - 1
  if (last < 0) return
  if (event.key === 'ArrowRight') active.value = Math.min(last, (active.value ?? -1) + 1)
  else if (event.key === 'ArrowLeft') active.value = Math.max(0, (active.value ?? last + 1) - 1)
  else if (event.key === 'Home') active.value = 0
  else if (event.key === 'End') active.value = last
  else if (event.key === 'Escape') active.value = null
  else return
  event.preventDefault()
}

onMounted(() => {
  if (!box.value) return
  width.value = box.value.clientWidth
  observer = new ResizeObserver(([entry]) => {
    if (entry) width.value = entry.contentRect.width
  })
  observer.observe(box.value)
})
onBeforeUnmount(() => observer?.disconnect())
</script>

<style scoped>
.ts-chart {
  position: relative;
  width: 100%;
}

.ts-chart__legend {
  display: flex;
  flex-wrap: wrap;
  gap: 4px 16px;
  margin: 0 0 4px 44px;
  font-size: 0.8125rem;
  color: var(--text-secondary);
}

.ts-chart__legend-item {
  display: inline-flex;
  align-items: center;
  gap: 6px;
}

.ts-chart__key {
  display: inline-block;
}

.ts-chart__key--bar {
  width: 10px;
  height: 10px;
  border-radius: 2px;
}

.ts-chart__key--line {
  width: 14px;
  height: 2px;
  border-radius: 1px;
}

.ts-chart__plot {
  position: relative;
}

svg {
  display: block;
  overflow: visible;
  outline: none;
}

svg:focus-visible {
  outline: 2px solid var(--q-primary);
  outline-offset: 2px;
  border-radius: 4px;
}

.ts-chart__grid line {
  stroke: var(--chart-grid);
  stroke-width: 1;
  shape-rendering: crispEdges;
}

.ts-chart__grid line.baseline {
  stroke: var(--chart-axis);
}

text {
  fill: var(--text-secondary);
  font-size: 12px;
  font-variant-numeric: tabular-nums;
}

.ts-chart__line {
  fill: none;
  stroke-width: 2;
  stroke-linejoin: round;
  stroke-linecap: round;
}

.ts-chart__dot {
  stroke: var(--chart-surface);
  stroke-width: 2;
}

.ts-chart__crosshair {
  stroke: var(--chart-axis);
  stroke-width: 1;
  shape-rendering: crispEdges;
}

.ts-chart__hit {
  fill: transparent;
}

path.dim {
  opacity: 0.55;
}

.ts-chart__empty {
  position: absolute;
  inset: 0;
  display: flex;
  align-items: center;
  justify-content: center;
}

.ts-chart--empty svg path,
.ts-chart--empty svg circle {
  display: none;
}

.ts-chart__tooltip {
  position: absolute;
  z-index: 1;
  pointer-events: none;
  min-width: 120px;
  padding: 6px 10px;
  border: 1px solid var(--border-color-muted);
  border-radius: 6px;
  background: var(--chart-surface);
  box-shadow: 0 2px 8px rgba(0, 0, 0, 0.12);
  font-size: 0.8125rem;
  white-space: nowrap;
}

.ts-chart__tooltip-date {
  color: var(--text-secondary);
  margin-bottom: 2px;
}

.ts-chart__tooltip-row {
  display: flex;
  align-items: center;
  gap: 6px;
}

.ts-chart__tooltip-key {
  width: 10px;
  height: 2px;
  border-radius: 1px;
}
</style>
