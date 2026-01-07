/**
 * API Service Module
 * 
 * Provides centralized HTTP client for all API requests with automatic
 * token authentication, error handling, and session management.
 * 
 * Features:
 * - Automatic token injection from localStorage
 * - Automatic 401 redirect to login
 * - Consistent error handling across app
 */

import axios from 'axios'
import config from './config'

/**
 * Create axios HTTP client instance with base configuration
 * 
 * Configuration:
 * - baseURL: Backend API URL from config (e.g., http://localhost:8000/api)
 * - Content-Type: application/json for all requests
 */
const api = axios.create({
  baseURL: config.apiUrl,
  headers: {
    'Content-Type': 'application/json'
  }
})

/**
 * Request Interceptor: Inject authentication token
 * 
 * Automatically adds Bearer token from localStorage to all requests
 * if token exists. This allows API to identify authenticated user.
 * 
 * Process:
 * 1. Check localStorage for 'authToken'
 * 2. If found, set Authorization header: "Token <token>"
 * 3. Forward request to server
 */
api.interceptors.request.use(
  (axiosConfig) => {
    const token = localStorage.getItem('authToken')
    if (token) {
      axiosConfig.headers.Authorization = `Token ${token}`
    }
    return axiosConfig
  },
  (error) => {
    return Promise.reject(error)
  }
)

/**
 * Response Interceptor: Handle authentication errors
 * 
 * Handles 401 Unauthorized responses (session expired or invalid token)
 * 
 * Process:
 * 1. Check if response status is 401
 * 2. Clear stored authentication data
 * 3. Redirect to login page if not already there
 * 4. Reject promise to notify caller of error
 */
api.interceptors.response.use(
  (response) => response,
  (error) => {
    if (error.response?.status === 401) {
      // Clear stored auth data on 401
      localStorage.removeItem('authToken')
      localStorage.removeItem('user')
      
      // Redirect to login if not already there
      if (window.location.pathname !== '/login') {
        window.location.href = '/login'
      }
    }
    return Promise.reject(error)
  }
)

export default api
