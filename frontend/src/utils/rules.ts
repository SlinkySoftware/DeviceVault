// SPDX-License-Identifier: GPL-3.0-or-later
// Quasar field validation rules.

export const required = (value: unknown): true | string =>
  (value !== null && value !== undefined && String(value).trim() !== '') || 'Required'

export const optionalNonNegativeInteger = (value: unknown): true | string =>
  value === null || value === undefined || value === '' || (Number.isInteger(Number(value)) && Number(value) >= 0)
    ? true
    : 'Must be a whole number of 0 or more'

export const integerBetween =
  (min: number, max: number) =>
  (value: unknown): true | string => {
    const n = Number(value)
    return (Number.isInteger(n) && n >= min && n <= max) || `Must be between ${min} and ${max}`
  }

export const hexColor = (value: unknown): true | string =>
  /^#[0-9a-f]{6}$/i.test(String(value)) || 'Use a hex colour such as #1976D2'
