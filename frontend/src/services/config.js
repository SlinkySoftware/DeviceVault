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
