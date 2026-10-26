// SPDX-License-Identifier: GPL-3.0-or-later

type Figure = number | string | null

/** A ratio figure (0-100), or a dash when there was nothing to measure. */
export function formatPercent(value: Figure): string {
  return typeof value === 'number' ? `${value.toFixed(1)} %` : '–'
}

/** Seconds as the largest sensible unit: 45 s, 12 min, 5.5 h, 3.2 d. */
export function formatAge(value: Figure): string {
  if (typeof value !== 'number') return '–'
  if (value < 120) return `${Math.round(value)} s`
  if (value < 7200) return `${Math.round(value / 60)} min`
  if (value < 2 * 86400) return `${(value / 3600).toFixed(1)} h`
  return `${(value / 86400).toFixed(1)} d`
}
