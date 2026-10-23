// SPDX-License-Identifier: GPL-3.0-or-later
import { useQuasar } from 'quasar'

import { apiErrorMessage } from '@/api/client'

/** Toast helpers with consistent placement and API error extraction. */
export function useNotify() {
  const $q = useQuasar()
  const show = (type: string, message: string) => $q.notify({ type, message, position: 'top' })

  return {
    success: (message: string) => show('positive', message),
    info: (message: string) => show('info', message),
    warning: (message: string) => show('warning', message),
    /** Show the API's own message when there is one, otherwise `fallback`. */
    error: (error: unknown, fallback: string) => show('negative', apiErrorMessage(error, fallback)),
  }
}
