/**
 * Timezone utility functions for DeviceVault frontend
 * 
 * This module handles timezone conversions between UTC (from API) and the configured
 * application timezone for display purposes.
 * 
 * Key principles:
 * - All timestamps from API are in UTC (ISO 8601 format)
 * - All user-facing displays use the configured timezone
 * - Timezone is fetched from the backend configuration
 */

let appTimezone = null

/**
 * Fetch and cache the application timezone from backend
 * @returns {Promise<string>} The timezone name (e.g., 'Australia/Sydney')
 */
export async function getAppTimezone() {
  if (appTimezone) {
    return appTimezone
  }
  
  try {
    const response = await fetch('/api/timezone/')
    const data = await response.json()
    appTimezone = data.timezone || 'UTC'
    return appTimezone
  } catch (error) {
    console.error('Failed to fetch timezone:', error)
    appTimezone = 'UTC'
    return appTimezone
  }
}

/**
 * Convert UTC ISO string to Date object in local timezone
 * @param {string} utcIsoString - ISO 8601 datetime string in UTC
 * @returns {Date} Date object
 */
export function utcToLocal(utcIsoString) {
  if (!utcIsoString) return null
  return new Date(utcIsoString)
}

/**
 * Format a UTC ISO string to local datetime string
 * @param {string} utcIsoString - ISO 8601 datetime string in UTC
 * @param {object} options - Intl.DateTimeFormat options
 * @returns {string} Formatted datetime string in local timezone
 */
export function formatDateTime(utcIsoString, options = {}) {
  if (!utcIsoString) return ''
  
  const date = utcToLocal(utcIsoString)
  const defaultOptions = {
    year: 'numeric',
    month: '2-digit',
    day: '2-digit',
    hour: '2-digit',
    minute: '2-digit',
    second: '2-digit',
    hour12: false
  }
  
  return date.toLocaleString(undefined, { ...defaultOptions, ...options })
}

/**
 * Format a UTC ISO string to local date string
 * @param {string} utcIsoString - ISO 8601 datetime string in UTC
 * @param {object} options - Intl.DateTimeFormat options
 * @returns {string} Formatted date string in local timezone
 */
export function formatDate(utcIsoString, options = {}) {
  if (!utcIsoString) return ''
  
  const date = utcToLocal(utcIsoString)
  const defaultOptions = {
    year: 'numeric',
    month: '2-digit',
    day: '2-digit'
  }
  
  return date.toLocaleDateString(undefined, { ...defaultOptions, ...options })
}

/**
 * Format a UTC ISO string to relative time (e.g., "5m ago", "2h ago")
 * @param {string} utcIsoString - ISO 8601 datetime string in UTC
 * @returns {string} Relative time string
 */
export function formatRelativeTime(utcIsoString) {
  if (!utcIsoString) return ''
  
  const date = utcToLocal(utcIsoString)
  const now = new Date()
  const diffMs = now - date
  const diffMins = Math.floor(diffMs / 60000)
  const diffHours = Math.floor(diffMs / 3600000)
  const diffDays = Math.floor(diffMs / 86400000)
  
  if (diffMins < 1) return 'Just now'
  if (diffMins < 60) return `${diffMins}m ago`
  if (diffHours < 24) return `${diffHours}h ago`
  if (diffDays < 7) return `${diffDays}d ago`
  
  return formatDate(utcIsoString)
}

/**
 * Format a UTC ISO string to short datetime (no seconds)
 * @param {string} utcIsoString - ISO 8601 datetime string in UTC
 * @returns {string} Formatted datetime string
 */
export function formatDateTimeShort(utcIsoString) {
  return formatDateTime(utcIsoString, {
    year: 'numeric',
    month: '2-digit',
    day: '2-digit',
    hour: '2-digit',
    minute: '2-digit',
    hour12: false
  })
}

/**
 * Get current local date/time
 * @returns {Date} Current date in local timezone
 */
export function now() {
  return new Date()
}

/**
 * Get date N days ago
 * @param {number} days - Number of days to go back
 * @returns {Date} Date N days ago
 */
export function daysAgo(days) {
  const date = new Date()
  date.setDate(date.getDate() - days)
  return date
}

/**
 * Convert local datetime to UTC ISO string for API submission
 * @param {Date} localDate - Date object in local timezone
 * @returns {string} ISO 8601 string in UTC
 */
export function localToUtc(localDate) {
  if (!localDate) return null
  return localDate.toISOString()
}

/**
 * Check if a datetime is today (in local timezone)
 * @param {string} utcIsoString - ISO 8601 datetime string in UTC
 * @returns {boolean} True if the date is today
 */
export function isToday(utcIsoString) {
  if (!utcIsoString) return false
  
  const date = utcToLocal(utcIsoString)
  const today = new Date()
  
  return date.getDate() === today.getDate() &&
         date.getMonth() === today.getMonth() &&
         date.getFullYear() === today.getFullYear()
}

/**
 * Get timezone offset string (e.g., "+10:00" for AEST)
 * @returns {string} Timezone offset
 */
export function getTimezoneOffset() {
  const offset = -new Date().getTimezoneOffset()
  const hours = Math.floor(Math.abs(offset) / 60)
  const minutes = Math.abs(offset) % 60
  const sign = offset >= 0 ? '+' : '-'
  return `${sign}${String(hours).padStart(2, '0')}:${String(minutes).padStart(2, '0')}`
}
