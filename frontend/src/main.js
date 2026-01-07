/**
 * Vue 3 Application Entry Point
 * 
 * Initializes and configures the DeviceVault frontend application with:
 * - Vue 3 framework
 * - Quasar UI components and Notify plugin
 * - Vue Router for client-side navigation
 * - Material Icons for UI icons
 */

import { createApp } from 'vue'
import { Quasar, Notify } from 'quasar'
import App from './App.vue'
import router from './router'

// Import Quasar CSS and Material Icons stylesheet
import 'quasar/dist/quasar.css'
import '@quasar/extras/material-icons/material-icons.css'

/**
 * Create Vue application instance
 * 
 * Mount point: #q-app element in index.html
 */
const app = createApp(App)

/**
 * Register Quasar framework with required plugins
 * 
 * Plugins:
 * - Notify: Toast notifications for user feedback
 */
app.use(Quasar, {
  plugins: {
    Notify
  }
})

/**
 * Register Vue Router for client-side navigation
 * Routes defined in ./router/index.js
 */
app.use(router)

/**
 * Mount Vue application to DOM element with id="q-app"
 */
app.mount('#q-app')
