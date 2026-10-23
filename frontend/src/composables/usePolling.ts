// SPDX-License-Identifier: GPL-3.0-or-later
import { onBeforeUnmount, onMounted, ref, watch, type Ref } from 'vue'

/**
 * Run `task` on mount and then every `intervalMs` until unmount. The interval
 * may be reactive; changing it reschedules. Ticks pause while the tab is hidden.
 */
export function usePolling(task: () => Promise<void> | void, intervalMs: Ref<number> | number) {
  const interval = typeof intervalMs === 'number' ? ref(intervalMs) : intervalMs
  let timer: ReturnType<typeof setInterval> | null = null

  const tick = () => {
    if (document.visibilityState !== 'hidden') void task()
  }
  const stop = () => {
    if (timer !== null) clearInterval(timer)
    timer = null
  }
  const start = () => {
    stop()
    timer = setInterval(tick, interval.value)
  }

  onMounted(() => {
    void task()
    start()
  })
  watch(interval, start)
  onBeforeUnmount(stop)

  return { stop, start }
}
