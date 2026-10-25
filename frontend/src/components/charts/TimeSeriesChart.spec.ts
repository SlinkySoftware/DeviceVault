// SPDX-License-Identifier: GPL-3.0-or-later
import { mount } from '@vue/test-utils'
import { afterEach, beforeEach, describe, expect, it } from 'vitest'
import { nextTick } from 'vue'

import TimeSeriesChart from './TimeSeriesChart.vue'
import type { ChartSeries } from './types'

const dates = ['2026-10-20', '2026-10-21', '2026-10-22']
const volume: ChartSeries[] = [
  { key: 'stored', label: 'Stored', color: 'blue', values: [3, 0, 5] },
  { key: 'failed', label: 'Failed', color: 'red', values: [1, 0, 0] },
]

let width: PropertyDescriptor | undefined
beforeEach(() => {
  width = Object.getOwnPropertyDescriptor(HTMLElement.prototype, 'clientWidth')
  Object.defineProperty(HTMLElement.prototype, 'clientWidth', { configurable: true, get: () => 600 })
})
afterEach(() => {
  if (width) Object.defineProperty(HTMLElement.prototype, 'clientWidth', width)
})

async function mountChart(props: Partial<InstanceType<typeof TimeSeriesChart>['$props']> = {}) {
  const wrapper = mount(TimeSeriesChart, { props: { dates, series: volume, kind: 'bar', label: 'Backups per day', ...props } })
  await nextTick() // the plot is drawn once its width is known
  return wrapper
}

describe('TimeSeriesChart', () => {
  it('stacks one segment per non-zero value', async () => {
    const paths = (await mountChart()).findAll('svg path')

    expect(paths.map((p) => p.attributes('fill'))).toEqual(['blue', 'red', 'blue'])
  })

  it('names every series in a legend and lists every value in a table', async () => {
    const wrapper = await mountChart()

    expect(wrapper.find('.ts-chart__legend').text()).toContain('Stored')
    expect(wrapper.find('.ts-chart__legend').text()).toContain('Failed')
    const rows = wrapper.findAll('tbody tr').map((row) => row.findAll('th, td').map((cell) => cell.text()))
    expect(rows[0]).toEqual(['Tue 20 Oct', '3', '1'])
    expect(wrapper.find('caption').text()).toBe('Backups per day')
  })

  it('has no legend for a single series', async () => {
    expect((await mountChart({ series: [volume[0]!] })).find('.ts-chart__legend').exists()).toBe(false)
  })

  it('shows a day with the arrow keys', async () => {
    const wrapper = await mountChart()
    const svg = wrapper.find('svg')

    await svg.trigger('keydown', { key: 'End' })
    expect(wrapper.find('.ts-chart__tooltip').text()).toContain('Thu 22 Oct')
    await svg.trigger('keydown', { key: 'ArrowLeft' })
    expect(wrapper.find('.ts-chart__tooltip').text()).toContain('Wed 21 Oct')
    await svg.trigger('keydown', { key: 'Escape' })
    expect(wrapper.find('.ts-chart__tooltip').exists()).toBe(false)
  })

  it('breaks a line where values are missing and formats them', async () => {
    const rate: ChartSeries[] = [{ key: 'rate', label: 'Rate', color: 'blue', values: [50, null, 100] }]
    const wrapper = await mountChart({ series: rate, kind: 'line', max: 100, format: (v: number) => `${v}%` })

    expect(wrapper.find('path.ts-chart__line').attributes('d')?.match(/M/g)).toHaveLength(2)
    expect(wrapper.findAll('circle')).toHaveLength(2) // both points are isolated
    expect(wrapper.findAll('tbody td').map((cell) => cell.text())).toEqual(['50%', '—', '100%'])
  })

  it('says when there is nothing to show', async () => {
    const empty = [{ key: 'stored', label: 'Stored', color: 'blue', values: [0, 0, 0] }]

    expect((await mountChart({ series: empty, emptyText: 'Nothing yet' })).find('.ts-chart__empty').text()).toBe('Nothing yet')
  })
})
