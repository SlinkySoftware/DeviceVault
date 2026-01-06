// Frontend configuration
// Use Vite-style env variable (VITE_API_URL); fallback to older VUE_APP_API_URL if present
const apiUrl = (typeof import.meta !== 'undefined' && import.meta.env && import.meta.env.VITE_API_URL)
  || (typeof process !== 'undefined' && process.env && process.env.VUE_APP_API_URL)
  || 'http://localhost:8000/api'

const config = {
  apiUrl,
  appName: 'DeviceVault',
  version: '1.0.0'
}

export default config
