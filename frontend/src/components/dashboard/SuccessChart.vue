<!-- SPDX-License-Identifier: GPL-3.0-or-later -->
<!-- Daily backup success-rate line chart drawn on a canvas. -->
<template>
  <div ref="container" class="chart">
    <canvas ref="canvas" role="img" :aria-label="ariaLabel" />
    <div v-if="data.length === 0" class="chart__empty text-muted">No backups in this period</div>
  </div>
</template>

<script setup lang="ts">
import { getCssVar, useQuasar } from 'quasar'
import { computed, onBeforeUnmount, onMounted, ref, watch } from 'vue'

import type { DailyStat } from '@/api/types'
import { calendarDayLabel } from '@/utils/datetime'

const props = defineProps<{ data: DailyStat[] }>()

const $q = useQuasar()
const container = ref<HTMLDivElement | null>(null)
const canvas = ref<HTMLCanvasElement | null>(null)
let resizeObserver: ResizeObserver | null = null

const ariaLabel = computed(() =>
  props.data.map((day) => `${day.date}: ${Math.round(day.rate)}%`).join(', ') || 'No data',
)

// Read the palette from the CSS variables so the chart follows the light/dark theme.
const cssColor = (name: string, fallback: string) => getCssVar(name) || fallback
const rateColor = (rate: number) =>
  rate >= 80 ? cssColor('positive', '#21BA45') : rate >= 50 ? cssColor('warning', '#F2C037') : cssColor('negative', '#C10015')

function draw(): void {
  const el = canvas.value
  const box = container.value
  const ctx = el?.getContext('2d')
  if (!el || !box || !ctx) return

  const { width, height } = box.getBoundingClientRect()
  const dpr = window.devicePixelRatio || 1
  el.width = width * dpr
  el.height = height * dpr
  el.style.width = `${width}px`
  el.style.height = `${height}px`
  ctx.setTransform(dpr, 0, 0, dpr, 0, 0)
  ctx.clearRect(0, 0, width, height)
  if (props.data.length === 0) return

  const dark = $q.dark.isActive
  const text = dark ? 'rgba(255, 255, 255, 0.6)' : 'rgba(0, 0, 0, 0.6)'
  const pad = { left: 44, right: 24, top: 28, bottom: 44 }
  const plotWidth = width - pad.left - pad.right
  const plotHeight = height - pad.top - pad.bottom
  const step = props.data.length > 1 ? plotWidth / (props.data.length - 1) : 0
  const x = (i: number) => pad.left + (props.data.length > 1 ? i * step : plotWidth / 2)
  const y = (rate: number) => height - pad.bottom - (rate / 100) * plotHeight

  ctx.font = '13px sans-serif'
  ctx.textAlign = 'right'
  ctx.lineWidth = 1
  for (const percent of [0, 25, 50, 75, 100]) {
    ctx.fillStyle = text
    ctx.fillText(`${percent}%`, pad.left - 8, y(percent) + 4)
    ctx.strokeStyle = dark ? 'rgba(255, 255, 255, 0.08)' : '#eee'
    ctx.beginPath()
    ctx.moveTo(pad.left, y(percent))
    ctx.lineTo(width - pad.right, y(percent))
    ctx.stroke()
  }

  ctx.strokeStyle = cssColor('primary', '#1976D2')
  ctx.lineWidth = 2
  ctx.beginPath()
  props.data.forEach((day, i) => {
    if (i === 0) {
      ctx.moveTo(x(i), y(day.rate))
      return
    }
    const prev = props.data[i - 1]!
    const mid = (x(i - 1) + x(i)) / 2
    ctx.bezierCurveTo(mid, y(prev.rate), mid, y(day.rate), x(i), y(day.rate))
  })
  ctx.stroke()

  ctx.textAlign = 'center'
  // Label every day when they fit, otherwise thin them out.
  const labelEvery = Math.max(1, Math.ceil(props.data.length / Math.max(1, Math.floor(plotWidth / 48))))
  props.data.forEach((day, i) => {
    ctx.fillStyle = rateColor(day.rate)
    ctx.beginPath()
    ctx.arc(x(i), y(day.rate), 4, 0, Math.PI * 2)
    ctx.fill()
    if (i % labelEvery !== 0) return
    const label = calendarDayLabel(day.date)
    ctx.fillStyle = text
    ctx.fillText(`${Math.round(day.rate)}%`, x(i), y(day.rate) - 10)
    ctx.fillText(label.weekday, x(i), height - pad.bottom + 16)
    ctx.fillText(String(label.day), x(i), height - pad.bottom + 31)
  })
}

watch(() => [props.data, $q.dark.isActive], draw, { deep: true })

onMounted(() => {
  draw()
  if (container.value) {
    resizeObserver = new ResizeObserver(draw)
    resizeObserver.observe(container.value)
  }
})

onBeforeUnmount(() => resizeObserver?.disconnect())
</script>

<style scoped>
.chart {
  position: relative;
  width: 100%;
  height: 100%;
  min-height: 240px;
}

canvas {
  display: block;
}

.chart__empty {
  position: absolute;
  inset: 0;
  display: flex;
  align-items: center;
  justify-content: center;
}
</style>
