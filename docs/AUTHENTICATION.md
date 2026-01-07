# DeviceVault Authentication Setup

## Overview

This document describes the authentication system for DeviceVault, including the login page, API authentication, and configuration.

## Frontend Components

### Login Page
- **Location**: `frontend/src/pages/Login.vue`
- **Features**:
  - Username and password authentication
  - "Remember me" functionality
  - Error handling and user feedback
  - Logo display using DeviceVault branding
  - Responsive design

### API Service (`frontend/src/services/api.js`)
- Configured to use backend URL from environment variables
- Automatically includes authentication token in all requests
- Handles 401 unauthorized responses by redirecting to login
- Token stored in localStorage

### Router Protection (`frontend/src/router/index.js`)
- Authentication guard on all protected routes
- Redirects unauthenticated users to login page
- Prevents authenticated users from accessing login page

### Configuration (`frontend/src/services/config.js`)
- **API URL**: Loaded from `VUE_APP_API_URL` environment variable
- Default: `http://localhost:8000/api`
- Can be overridden in `.env` or `.env.production`

## Backend Components

### Authentication Endpoints

#### POST `/api/auth/login/`
Authenticates user and returns token

**Request**:
```json
{
  "username": "admin",
  "password": "admin123"
}
```

**Response** (200 OK):
```json
{
  "token": "abcd1234efgh5678",
  "user": {
    "id": 1,
    "username": "admin",
    "email": "admin@example.com",
    "first_name": "Admin",
    "last_name": "User"
  }
}
```

#### POST `/api/auth/logout/`
Logs out authenticated user

**Headers**: 
```
Authorization: Token <token>
```

**Response** (200 OK):
```json
{
  "message": "Logged out successfully"
}
```

#### GET `/api/auth/user/`
Returns current authenticated user info

**Headers**:
```
Authorization: Token <token>
```

**Response** (200 OK):
```json
{
  "id": 1,
  "username": "admin",
  "email": "admin@example.com",
  "first_name": "Admin",
  "last_name": "User"
}
```

### Authentication Configuration

**Backend Settings** (`backend/devicevault/settings.py`):
- Token-based authentication enabled
- Session authentication for backward compatibility
- Basic authentication for development
- CORS credentials enabled for cross-origin requests

**Installed Apps**:
```python
'rest_framework.authtoken'  # Token authentication
```

**REST Framework Settings**:
```python
'DEFAULT_AUTHENTICATION_CLASSES': [
    'rest_framework.authentication.TokenAuthentication',
    'rest_framework.authentication.SessionAuthentication',
    'rest_framework.authentication.BasicAuthentication'
]
'DEFAULT_PERMISSION_CLASSES': [
    'rest_framework.permissions.IsAuthenticatedOrReadOnly'
]
```

## Setup Instructions

### 1. Database Migrations
Run Django migrations to create authentication token tables:

```bash
cd backend
python manage.py migrate
```

### 2. Create Admin User
Create a default admin user:

```bash
python manage.py create_admin --username admin --password admin123 --email admin@devicevault.local
```

Or use Django's built-in command:
```bash
python manage.py createsuperuser
```

### 3. Configure Frontend API URL

#### Development (.env)
```
VUE_APP_API_URL=http://localhost:8000/api
```

#### Production (.env.production)
```
VUE_APP_API_URL=https://your-domain.com/api
```

### 4. Start Frontend Development Server
```bash
cd frontend
npm install
npm run dev
```

Frontend will be available at: `http://localhost:9000`
Access the login page directly

### 5. Start Backend Server
```bash
cd backend
python manage.py runserver 8000
```

Backend API will be available at: `http://localhost:8000/api`

## Environment Variables

### Frontend

| Variable | Default | Description |
|----------|---------|-------------|
| `VUE_APP_API_URL` | `http://localhost:8000/api` | Backend API base URL |

### Backend

| Variable | Default | Description |
|----------|---------|-------------|
| `DEVICEVAULT_SECRET_KEY` | `dev-secret` | Django secret key |
| `DEVICEVAULT_CONFIG` | `config/config.yaml` | Configuration file path |

## Security Considerations

1. **Token Storage**: Tokens are stored in localStorage. For production:
   - Consider using httpOnly cookies instead
   - Implement token refresh mechanism
   - Add CSRF protection

2. **HTTPS**: Always use HTTPS in production

3. **CORS**: Current settings allow all origins. For production:
   ```python
   CORS_ALLOWED_ORIGINS = [
       'https://your-domain.com'
   ]
   ```

4. **Default Credentials**: Change default admin password immediately

## API Authorization Examples

### Python (requests)
```python
import requests

token = 'your-auth-token'
headers = {'Authorization': f'Token {token}'}

response = requests.get(
    'http://localhost:8000/api/devices/',
    headers=headers
)
```

### JavaScript (axios)
```javascript
const token = localStorage.getItem('authToken')
api.defaults.headers.common['Authorization'] = `Token ${token}`

api.get('/devices/')
```

### cURL
```bash
curl -H "Authorization: Token your-auth-token" \
  http://localhost:8000/api/devices/
```

## Troubleshooting

### Login Returns 401
- Check username and password
- Ensure user exists: `python manage.py shell` then `User.objects.all()`
- Verify database migrations ran: `python manage.py migrate`

### Token Not Sent to Backend
- Check localStorage in browser DevTools
- Verify API URL in .env matches backend address
- Check CORS settings in Django

### Unauthorized on API Calls
- Verify token is valid and not expired
- Check API endpoint permissions
- Ensure token is prefixed with "Token " (not "Bearer")

## Future Enhancements

1. OAuth2/Social authentication (already has social-auth-app-django)
2. LDAP authentication (django-auth-ldap installed)
3. SAML authentication (djangosaml2 installed)
4. Two-factor authentication
5. Token refresh mechanism
6. Role-based access control (RBAC infrastructure exists)
