// SPDX-License-Identifier: GPL-3.0-or-later
import { mount } from '@vue/test-utils'
import { describe, expect, it } from 'vitest'
import { defineComponent, h, ref } from 'vue'

import JsonEditor from './JsonEditor.vue'

function mountEditor(initial: Record<string, unknown>) {
  const updates: unknown[] = []
  const wrapper = mount(JsonEditor, {
    props: { modelValue: initial, 'onUpdate:modelValue': (value: unknown) => updates.push(value) },
  })
  return { wrapper, updates, textarea: () => wrapper.get('textarea') }
}

describe('JsonEditor', () => {
  it('keeps half-typed invalid JSON instead of reverting it', async () => {
    const { textarea, updates } = mountEditor({})

    await textarea().setValue('{"pass')

    expect((textarea().element as HTMLTextAreaElement).value).toBe('{"pass')
    expect(updates).toEqual([])
  })

  it('emits the parsed object once the text is valid', async () => {
    const { textarea, updates } = mountEditor({})

    await textarea().setValue('{"password": "secret"}')

    expect(updates).toEqual([{ password: 'secret' }])
  })

  it('rejects JSON that is not an object', async () => {
    const { textarea, updates } = mountEditor({})

    await textarea().setValue('[1, 2]')

    expect(updates).toEqual([])
  })

  it('shows a new value given from outside', async () => {
    const { wrapper, textarea } = mountEditor({ a: 1 })

    await wrapper.setProps({ modelValue: { b: 2 } })

    expect(JSON.parse((textarea().element as HTMLTextAreaElement).value)).toEqual({ b: 2 })
  })

  it('does not rewrite the text when a reactive parent stores the value', async () => {
    // Real pages keep the object in reactive state, so it comes back proxied.
    const Parent = defineComponent(() => {
      const data = ref<Record<string, unknown>>({ a: 1 })
      return () => h(JsonEditor, { modelValue: data.value, 'onUpdate:modelValue': (v) => (data.value = v) })
    })
    const wrapper = mount(Parent)
    const textarea = wrapper.get('textarea')

    await textarea.setValue('')
    expect((textarea.element as HTMLTextAreaElement).value).toBe('')

    await textarea.setValue('{"b":2}')
    expect((textarea.element as HTMLTextAreaElement).value).toBe('{"b":2}')
  })
})
