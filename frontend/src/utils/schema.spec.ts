// SPDX-License-Identifier: GPL-3.0-or-later
import { describe, expect, it } from 'vitest'

import { checkField, keepKnown, schemaFields, type JsonSchema } from './schema'

// What pydantic generates for the MikroTik and demo drivers' Params models.
const SCHEMA: JsonSchema = {
  type: 'object',
  additionalProperties: false,
  properties: {
    port: { type: 'integer', minimum: 1, maximum: 65535, default: 22, title: 'Port', description: 'SSH port' },
    show_sensitive: { type: 'boolean', default: true, title: 'Show Sensitive' },
    hostname: { anyOf: [{ type: 'string' }, { type: 'null' }], default: null, title: 'Hostname' },
    mode: { $ref: '#/$defs/Mode' },
    tags: { type: 'array', items: { type: 'string' } },
    nested: { type: 'object' },
  },
  required: ['tags'],
  $defs: { Mode: { enum: ['fast', 'safe'], type: 'string', title: 'Mode' } },
}

describe('schemaFields', () => {
  const { fields, unsupported } = schemaFields(SCHEMA)
  const byName = Object.fromEntries(fields.map((f) => [f.name, f]))

  it('maps pydantic property shapes to form fields', () => {
    expect(fields.map((f) => [f.name, f.kind])).toEqual([
      ['port', 'integer'],
      ['show_sensitive', 'boolean'],
      ['hostname', 'string'],
      ['mode', 'enum'],
      ['tags', 'list'],
    ])
    expect(byName.port).toMatchObject({ label: 'Port', default: 22, min: 1, max: 65535, description: 'SSH port' })
    expect(byName.hostname).toMatchObject({ nullable: true, default: null })
    expect(byName.mode!.options).toEqual(['fast', 'safe'])
    expect(byName.tags!.label).toBe('Tags')
  })

  it('reports properties it cannot render', () => {
    expect(unsupported).toEqual(['nested'])
  })

  it('validates values', () => {
    expect(checkField(byName.port!, 0)).toBe('Port must be at least 1')
    expect(checkField(byName.port!, 2.5)).toBe('Port must be a whole number')
    expect(checkField(byName.port!, undefined)).toBe(true)
    expect(checkField(byName.tags!, undefined)).toBe('Tags is required')
  })
})

describe('keepKnown', () => {
  it('drops parameters the new driver does not have', () => {
    expect(keepKnown({ port: 2222, interfaces: 4 }, SCHEMA)).toEqual({ port: 2222 })
    expect(keepKnown({ port: 2222 }, null)).toEqual({})
  })
})

describe('secret settings', () => {
  it('marks write-only and password fields as secret', () => {
    const { fields } = schemaFields({
      properties: {
        key: { anyOf: [{ type: 'string', writeOnly: true, format: 'password' }, { type: 'null' }], default: null },
        bucket: { type: 'string' },
      },
    })

    expect(fields.map((f) => [f.name, f.secret])).toEqual([
      ['key', true],
      ['bucket', false],
    ])
  })
})
