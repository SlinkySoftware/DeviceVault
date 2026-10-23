// SPDX-License-Identifier: GPL-3.0-or-later
// Form fields from a collector driver's parameter schema (the JSON schema
// pydantic generates for the driver's Params model).

import type { JsonObject } from '@/api/types'

export interface JsonSchema {
  type?: string | string[]
  title?: string
  description?: string
  default?: unknown
  enum?: unknown[]
  minimum?: number
  maximum?: number
  exclusiveMinimum?: number
  exclusiveMaximum?: number
  minLength?: number
  maxLength?: number
  items?: JsonSchema
  anyOf?: JsonSchema[]
  properties?: Record<string, JsonSchema>
  required?: string[]
  writeOnly?: boolean
  format?: string
  additionalProperties?: boolean | JsonSchema
  $ref?: string
  $defs?: Record<string, JsonSchema>
}

export type FieldKind = 'boolean' | 'integer' | 'number' | 'string' | 'enum' | 'list'

export interface SchemaField {
  name: string
  kind: FieldKind
  label: string
  description: string
  default: unknown
  required: boolean
  nullable: boolean
  /** Write-only (a password or key): never shown, only replaced. */
  secret: boolean
  /** Multi-line text, e.g. a PEM certificate (`format: "multiline"`). */
  multiline: boolean
  options: unknown[]
  min: number | undefined
  max: number | undefined
}

/** Title Case from a property name, for schemas without titles. */
function labelFor(name: string): string {
  return name.replace(/_/g, ' ').replace(/^\w/, (c) => c.toUpperCase())
}

function resolve(schema: JsonSchema, root: JsonSchema): JsonSchema {
  const match = schema.$ref?.match(/^#\/\$defs\/(.+)$/)
  const target = match ? root.$defs?.[match[1]!] : undefined
  if (!target) return schema
  const { $ref: _ref, ...rest } = schema
  return { ...target, ...rest }
}

function kindOf(schema: JsonSchema): FieldKind | null {
  if (schema.enum) return 'enum'
  switch (schema.type) {
    case 'boolean':
    case 'integer':
    case 'number':
    case 'string':
      return schema.type
    case 'array':
      return schema.items && kindOf(schema.items) === 'string' ? 'list' : null
    default:
      return null
  }
}

/**
 * The form fields for `schema`'s properties. `unsupported` lists properties
 * the form cannot render (nested objects, unions); callers fall back to a
 * JSON editor for those.
 */
export function schemaFields(schema: JsonSchema | null | undefined): { fields: SchemaField[]; unsupported: string[] } {
  const fields: SchemaField[] = []
  const unsupported: string[] = []
  if (!schema?.properties) return { fields, unsupported }
  for (const [name, raw] of Object.entries(schema.properties)) {
    let property = resolve(raw, schema)
    let nullable = false
    // Optional values arrive as anyOf [X, null].
    if (property.anyOf) {
      const others = property.anyOf.map((s) => resolve(s, schema)).filter((s) => s.type !== 'null')
      nullable = others.length < property.anyOf.length
      if (others.length !== 1) {
        unsupported.push(name)
        continue
      }
      const { anyOf: _anyOf, ...rest } = property
      property = { ...others[0], ...rest }
    }
    const kind = kindOf(property)
    if (!kind) {
      unsupported.push(name)
      continue
    }
    fields.push({
      name,
      kind,
      label: property.title || labelFor(name),
      description: property.description ?? '',
      default: property.default,
      required: (schema.required ?? []).includes(name),
      nullable,
      secret: Boolean(property.writeOnly) || property.format === 'password',
      multiline: property.format === 'multiline',
      options: property.enum ?? [],
      min: property.minimum ?? (property.exclusiveMinimum !== undefined ? property.exclusiveMinimum + 1 : undefined),
      max: property.maximum ?? (property.exclusiveMaximum !== undefined ? property.exclusiveMaximum - 1 : undefined),
    })
  }
  return { fields, unsupported }
}

/** Only the parameters `schema` knows about; used when the backup method changes. */
export function keepKnown(params: JsonObject, schema: JsonSchema | null | undefined): JsonObject {
  if (!schema?.properties) return {}
  return Object.fromEntries(Object.entries(params).filter(([name]) => name in schema.properties!))
}

/** An error message for `value`, or true when it is acceptable. */
export function checkField(field: SchemaField, value: unknown): true | string {
  if (value === undefined || value === null || value === '') {
    return field.required && field.default === undefined ? `${field.label} is required` : true
  }
  if (field.kind === 'integer' && !Number.isInteger(value)) return `${field.label} must be a whole number`
  if ((field.kind === 'integer' || field.kind === 'number') && typeof value === 'number') {
    if (field.min !== undefined && value < field.min) return `${field.label} must be at least ${field.min}`
    if (field.max !== undefined && value > field.max) return `${field.label} must be at most ${field.max}`
  }
  return true
}
