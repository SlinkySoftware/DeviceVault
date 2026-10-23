// SPDX-License-Identifier: GPL-3.0-or-later
// Shared list + create/edit dialog + delete behaviour for admin CRUD pages.

import { useQuasar } from 'quasar'
import { computed, onMounted, ref, type Ref } from 'vue'

import type { ResourceApi } from '@/api/endpoints'
import type { Id } from '@/api/types'

import { useNotify } from './useNotify'

export interface CrudOptions<T extends { id: Id }, F> {
  api: Pick<ResourceApi<T, F>, 'list' | 'create' | 'update' | 'remove'>
  /** Singular, lower case: "device type". */
  noun: string
  emptyForm: () => F
  /** Form values for editing `row`; defaults to a copy of the row. */
  toForm?: (row: T) => F
  /** How a row is named in the delete confirmation; defaults to `row.name`. */
  describe?: (row: T) => string
  /** Fetch on mount (default true). */
  immediate?: boolean
}

export function useCrud<T extends { id: Id }, F extends object>(options: CrudOptions<T, F>) {
  const $q = useQuasar()
  const notify = useNotify()
  const toForm = options.toForm ?? ((row: T) => ({ ...row }) as unknown as F)
  const describe = options.describe ?? ((row: T) => String((row as { name?: unknown }).name ?? row.id))
  const label = options.noun.charAt(0).toUpperCase() + options.noun.slice(1)

  const rows = ref([]) as Ref<T[]>
  const loading = ref(false)
  const saving = ref(false)
  const dialogOpen = ref(false)
  const editingId = ref<Id | null>(null)
  const form = ref(options.emptyForm()) as Ref<F>
  const isEditing = computed(() => editingId.value !== null)

  async function load(): Promise<void> {
    loading.value = true
    try {
      rows.value = await options.api.list()
    } catch (error) {
      notify.error(error, `Failed to load ${options.noun}s`)
    } finally {
      loading.value = false
    }
  }

  function openCreate(): void {
    editingId.value = null
    form.value = options.emptyForm()
    dialogOpen.value = true
  }

  function openEdit(row: T): void {
    editingId.value = row.id
    form.value = toForm(row)
    dialogOpen.value = true
  }

  async function save(): Promise<boolean> {
    saving.value = true
    try {
      if (editingId.value !== null) {
        await options.api.update(editingId.value, form.value)
        notify.success(`${label} updated`)
      } else {
        await options.api.create(form.value)
        notify.success(`${label} created`)
      }
      dialogOpen.value = false
      await load()
      return true
    } catch (error) {
      notify.error(error, `Failed to save ${options.noun}`)
      return false
    } finally {
      saving.value = false
    }
  }

  function confirmRemove(row: T, extraWarning?: string): void {
    $q.dialog({
      title: `Delete ${options.noun}`,
      message: `Delete ${options.noun} "${describe(row)}"?${extraWarning ? ` ${extraWarning}` : ''}`,
      cancel: true,
      persistent: true,
      ok: { label: 'Delete', color: 'negative' },
    }).onOk(async () => {
      try {
        await options.api.remove(row.id)
        notify.success(`${label} deleted`)
        await load()
      } catch (error) {
        notify.error(error, `Failed to delete ${options.noun}`)
      }
    })
  }

  if (options.immediate !== false) onMounted(load)

  return { rows, loading, saving, dialogOpen, form, isEditing, load, openCreate, openEdit, save, confirmRemove }
}
