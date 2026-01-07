/**
 * Frontend Configuration Module
 * 
 * Provides centralized configuration for frontend application.
 * Environment variables are checked in order of preference:
 * 1. VITE_API_URL (Vite environment variable - preferred)
 * 2. VUE_APP_API_URL (Vue CLI environment variable - legacy)
 * 3. Default to http://localhost:8000/api for local development
 */

/**
 * Determine API URL from environment configuration
 * 
 * Build-time configuration:
 * - Set VITE_API_URL in .env file (Vite)
 * - Or VUE_APP_API_URL in .env file (Vue CLI legacy)
 * - Defaults to http://localhost:8000/api for development
 * 
 * @type {string}
 */
const apiUrl = (typeof import.meta !== 'undefined' && import.meta.env && import.meta.env.VITE_API_URL)
  || (typeof process !== 'undefined' && process.env && process.env.VUE_APP_API_URL)
  || 'http://localhost:8000/api'

/**
 * Application Configuration Object
 * 
 * Properties:
 * - apiUrl (string): Base URL for all API requests
 * - appName (string): Application display name
 * - version (string): Application version number
 */
const config = {
  apiUrl,
  appName: 'DeviceVault',
  version: '1.0.0'
}

export default config
