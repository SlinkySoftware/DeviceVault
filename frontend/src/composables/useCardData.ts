// SPDX-License-Identifier: GPL-3.0-or-later
import { onMounted, ref, watch, type Ref, type WatchSource } from 'vue'

/**
 * Data for one dashboard card: loaded on mount and whenever `source` changes. A reload
 * keeps the previous data (the card dims it) and a failure keeps it too, setting `failed`.
 */
export function useCardData<T>(load: () => Promise<T>, source?: WatchSource) {
  const data = ref<T | null>(null) as Ref<T | null>
  const loading = ref(false)
  const failed = ref(false)

  async function refresh(): Promise<void> {
    loading.value = true
    try {
      data.value = await load()
      failed.value = false
    } catch {
      failed.value = true
    } finally {
      loading.value = false
    }
  }

  onMounted(refresh)
  if (source) watch(source, refresh)

  return { data, loading, failed, refresh }
}
