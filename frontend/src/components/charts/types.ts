// SPDX-License-Identifier: GPL-3.0-or-later

export interface ChartSeries {
  key: string
  label: string
  /** A CSS colour, normally one of the `--chart-*` variables. */
  color: string
  /** One per date; null where there is no value (a gap in a line). */
  values: (number | null)[]
}

export interface BarRow {
  key: string
  label: string
  value: number
  /** The value as shown. */
  display: string
  /** A second line under the label. */
  caption?: string
}
