// SPDX-License-Identifier: GPL-3.0-or-later

/** Offer `content` to the user as a file download. */
export function saveFile(content: Blob | string, filename: string, type = 'text/plain;charset=utf-8'): void {
  const blob = typeof content === 'string' ? new Blob([content], { type }) : content
  const url = URL.createObjectURL(blob)
  const link = document.createElement('a')
  link.href = url
  link.download = filename
  link.style.display = 'none'
  document.body.appendChild(link)
  link.click()
  link.remove()
  // Revoke after the click has been handled.
  setTimeout(() => URL.revokeObjectURL(url), 0)
}

/** Make a string safe to use as a filename component. */
export function safeFilename(value: string): string {
  return value.replace(/[^\w.-]+/g, '_').replace(/^_+|_+$/g, '') || 'file'
}
