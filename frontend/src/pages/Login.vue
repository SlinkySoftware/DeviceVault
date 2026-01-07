<template>
  <q-page class="login-page">
    <div class="login-container">
      <div class="login-card">
        <!-- Logo -->
        <div class="logo-section">
          <img src="/logos/dv-mini-logo.png" alt="DeviceVault" class="logo" />
          <h1>DeviceVault</h1>
          <p class="subtitle">Device Backup Management System</p>
        </div>

        <!-- Error Messages -->
        <q-banner
          v-if="error"
          class="bg-red-2 text-red-9 q-mb-md"
          dense
          rounded
        >
          <template v-slot:avatar>
            <q-icon name="error" />
          </template>
          {{ error }}
        </q-banner>

        <!-- Login Form -->
        <q-form @submit.prevent="handleLogin" class="login-form">
          <q-input
            v-model="form.username"
            type="text"
            label="Username"
            outlined
            dense
            class="q-mb-md"
            :disable="loading"
            :rules="[(val) => val && val.length > 0 || 'Username is required']"
          >
            <template v-slot:prepend>
              <q-icon name="person" />
            </template>
          </q-input>

          <q-input
            v-model="form.password"
            type="password"
            label="Password"
            outlined
            dense
            class="q-mb-lg"
            :disable="loading"
            :rules="[(val) => val && val.length > 0 || 'Password is required']"
          >
            <template v-slot:prepend>
              <q-icon name="lock" />
            </template>
          </q-input>

          <q-checkbox
            v-model="form.rememberMe"
            label="Remember me"
            class="q-mb-lg"
          />

          <q-btn
            type="submit"
            color="primary"
            label="Login"
            class="full-width"
            :loading="loading"
            size="lg"
          />
        </q-form>

        <!-- Footer -->
        <div class="footer">
          <p>&copy; 2026 DeviceVault. All rights reserved.</p>
        </div>
      </div>
    </div>
  </q-page>
</template>

<script>
import api from '../services/api'

export default {
  name: 'LoginPage',
  data() {
    return {
      form: {
        username: '',
        password: '',
        rememberMe: false
      },
      loading: false,
      error: null
    }
  },
  methods: {
    async handleLogin() {
      this.error = null
      this.loading = true

      try {
        // Send login request to backend
        const response = await api.post('/auth/login/', {
          username: this.form.username,
          password: this.form.password
        })

        // Store authentication token and user info
        localStorage.setItem('authToken', response.data.token)
        localStorage.setItem('user', JSON.stringify(response.data.user))

        if (this.form.rememberMe) {
          localStorage.setItem('rememberMe', 'true')
          localStorage.setItem('username', this.form.username)
        }

        // Update API headers with token
        api.defaults.headers.common['Authorization'] = `Token ${response.data.token}`

        // Redirect to dashboard
        this.$router.push('/')

        this.$q.notify({
          type: 'positive',
          message: 'Login successful!',
          position: 'top'
        })
      } catch (error) {
        this.error =
          error.response?.data?.message ||
          error.response?.data?.detail ||
          'Login failed. Please check your credentials.'

        this.$q.notify({
          type: 'negative',
          message: this.error,
          position: 'top'
        })
      } finally {
        this.loading = false
      }
    }
  },
  mounted() {
    // Pre-fill username if remember me was used
    if (localStorage.getItem('rememberMe') === 'true') {
      this.form.username = localStorage.getItem('username') || ''
    }

    // Redirect to dashboard if already logged in
    if (localStorage.getItem('authToken')) {
      this.$router.push('/')
    }
  }
}
</script>

<style scoped>
.login-page {
  background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
  display: flex;
  align-items: center;
  justify-content: center;
  min-height: 100vh;
  font-family: 'Segoe UI', Tahoma, Geneva, Verdana, sans-serif;
}

.login-container {
  width: 100%;
  max-width: 400px;
  padding: 20px;
}

.login-card {
  background: white;
  border-radius: 12px;
  box-shadow: 0 10px 40px rgba(0, 0, 0, 0.2);
  padding: 40px;
  color: #333;
}

:deep(.body--dark) .login-card {
  background: #1e1e1e;
  color: #fff;
}

:deep(.body--dark) .login-card .logo-section h1 {
  color: #fff;
}

:deep(.body--dark) .login-card .logo-section .subtitle {
  color: #b0b0b0;
}

:deep(.body--dark) .login-card .footer {
  color: #808080;
  border-top-color: #333;
}

/* Force light styling for form inputs */
.login-form :deep(.q-field__control) {
  background-color: #fff !important;
  color: #333 !important;
}

.login-form :deep(.q-field__label) {
  color: #666 !important;
}

.login-form :deep(.q-field--outlined .q-field__control::before) {
  border-color: #2196f3 !important;
}

.login-form :deep(.q-field--outlined.q-field--focused .q-field__control::before) {
  border-color: #1976d2 !important;
}

.login-form :deep(.q-field__native),
.login-form :deep(.q-field__input) {
  color: #333 !important;
  caret-color: #333 !important;
}

/* Checkbox styling */
.login-form :deep(.q-checkbox__inner) {
  color: #2196f3 !important;
}

.login-form :deep(.q-checkbox__label) {
  color: #333 !important;
}

/* Input icon colors */
.login-form :deep(.q-icon) {
  color: #666 !important;
}

/* Placeholder text */
.login-form :deep(.q-field__input::placeholder) {
  color: #999 !important;
}

.logo-section {
  text-align: center;
  margin-bottom: 40px;
}
.logo-section .logo {
  max-width: 120px;
  height: auto;
  margin-bottom: 20px;
}
.logo-section h1 {
  font-size: 28px;
  font-weight: 600;
  color: #333;
  margin: 10px 0;
}
.logo-section .subtitle {
  color: #666;
  font-size: 14px;
  margin: 0;
}

.login-form {
  margin-bottom: 20px;
}

.footer {
  text-align: center;
  color: #999;
  font-size: 12px;
  margin-top: 20px;
  border-top: 1px solid #eee;
  padding-top: 20px;

  p {
    margin: 0;
  }
}

/* Mobile responsiveness */
@media (max-width: 480px) {
  .login-card {
    padding: 30px 20px;
  }

  .logo-section h1 {
    font-size: 24px;
  }
}
</style>
