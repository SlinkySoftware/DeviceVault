/*
* DeviceVault - A comprehensive network device backup management application with web interface for user and admin access and backend component for automated backup collection.
* Copyright (C) 2026, Slinky Software
*
* This program is free software: you can redistribute it and/or modify
* it under the terms of the GNU General Public License as published by
* the Free Software Foundation, either version 3 of the License, or
* (at your option) any later version.
*
* This program is distributed in the hope that it will be useful,
* but WITHOUT ANY WARRANTY; without even the implied warranty of
* MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
* GNU General Public License for more details.
*
* You should have received a copy of the GNU General Public License
* along with this program.  If not, see <http://www.gnu.org/licenses/>.
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
