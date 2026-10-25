// SPDX-License-Identifier: GPL-3.0-or-later
// Axis arithmetic shared by the chart components.

/** Round `value` up to 1, 2, 2.5 or 5 times a power of ten. */
function niceStep(value: number): number {
  const power = 10 ** Math.floor(Math.log10(value))
  const fraction = value / power
  const nice = fraction <= 1 ? 1 : fraction <= 2 ? 2 : fraction <= 2.5 ? 2.5 : fraction <= 5 ? 5 : 10
  return nice * power
}

/**
 * Evenly spaced ticks from 0 covering `max`, about `count` of them. A fixed `max`
 * (such as 100 for percentages) is used as is; with no data the axis is 0 to 1. Counts (`integer`)
 * never get a fractional step.
 */
export function niceTicks(max: number, count = 4, fixed = false, integer = false): number[] {
  if (fixed) {
    const step = max / count
    return Array.from({ length: count + 1 }, (_, i) => i * step)
  }
  if (!(max > 0)) return [0, 1]
  const step = integer ? Math.max(1, niceStep(max / count)) : niceStep(max / count)
  const ticks = []
  for (let tick = 0; tick < max + step / 2; tick += step) ticks.push(Number(tick.toPrecision(12)))
  if (ticks[ticks.length - 1]! < max) ticks.push(Number((ticks.length * step).toPrecision(12)))
  return ticks
}

/** Show every `n`th of `count` labels so that each gets about `minWidth` pixels of `width`. */
export function labelEvery(count: number, width: number, minWidth: number): number {
  if (count <= 0 || width <= 0) return 1
  return Math.max(1, Math.ceil(count / Math.max(1, Math.floor(width / minWidth))))
}

/** Compact axis numbers: 950, 1.2K, 3.4M. */
export function compactNumber(value: number): string {
  if (Math.abs(value) < 1000) return String(Math.round(value * 10) / 10)
  return new Intl.NumberFormat('en', { notation: 'compact', maximumFractionDigits: 1 }).format(value)
}
