import axios from 'axios'
import config from './config'

// Create axios instance with base URL from config
const api = axios.create({
  baseURL: config.apiUrl,
  headers: {
    'Content-Type': 'application/json'
  }
})

// Add token to requests if it exists
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

// Handle 401 responses (unauthorized)
api.interceptors.response.use(
  (response) => response,
  (error) => {
    if (error.response?.status === 401) {
      // Clear stored auth data
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
