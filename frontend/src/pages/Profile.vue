<template>
  <q-page class="q-pa-md">
    <q-card>
      <q-card-section class="row items-center">
        <q-avatar size="64px" class="q-mr-md">
          <q-icon name="person" size="48px" />
        </q-avatar>
        <div>
          <div class="text-h6">{{ user?.username || 'User' }}</div>
          <div class="text-subtitle2">{{ fullName }}</div>
          <div class="text-caption text-grey q-mt-xs" v-if="!editable">Managed by external identity provider</div>
        </div>
      </q-card-section>
      <q-separator />
      <q-card-section>
        <q-form @submit="save" class="q-gutter-md">
          <q-input v-model="user.username" label="Username" disable />
          <q-input v-model="user.email" label="Email" :disable="!editable" />
          <q-input v-model="user.first_name" label="First Name" :disable="!editable" />
          <q-input v-model="user.last_name" label="Last Name" :disable="!editable" />
          <div class="q-mt-md">
            <q-btn v-if="editable" type="submit" color="primary" label="Save" :loading="loading" />
          </div>
        </q-form>
      </q-card-section>
      <q-separator />
      <q-card-section>
        <div class="text-subtitle1 q-mb-md">Theme Preference</div>
        <q-select 
          v-model="theme" 
          :options="themeOptions" 
          label="Theme" 
          emit-value 
          map-options
          @update:model-value="saveTheme"
        />
      </q-card-section>
      <q-separator />
      <q-card-section>
        <div class="text-subtitle1 q-mb-md">Change Password</div>
        <q-form @submit="changePassword" class="q-gutter-md">
          <q-input v-model="pwd.current" type="password" label="Current Password" :disable="!editable" />
          <q-input v-model="pwd.new1" type="password" label="New Password" :disable="!editable" />
          <q-input v-model="pwd.new2" type="password" label="Confirm New Password" :disable="!editable" />
          <div class="q-mt-md">
            <q-btn v-if="editable" type="submit" color="primary" label="Update Password" :loading="pwdLoading" />
          </div>
        </q-form>
      </q-card-section>
    </q-card>
  </q-page>
</template>

<script>
import { defineComponent } from 'vue'
import { useQuasar } from 'quasar'
import api from '../services/api'

export default defineComponent({
  name: 'ProfilePage',
  setup() {
    return {
      $q: useQuasar()
    }
  },
  data() {
    return {
      user: {
        username: '',
        email: '',
        first_name: '',
        last_name: ''
      },
      editable: false,
      loading: false,
      pwd: { current: '', new1: '', new2: '' },
      pwdLoading: false,
      error: null,
      theme: 'dark',
      themeOptions: [
        { label: 'Dark Mode', value: 'dark' },
        { label: 'Light Mode', value: 'light' }
      ]
    }
  },
  computed: {
    fullName() {
      const f = this.user.first_name || ''
      const l = this.user.last_name || ''
      return (f + ' ' + l).trim() || this.user.username
    }
  },
  async mounted() {
    this.loading = true
    try {
      const res = await api.get('/auth/user/')
      this.user = {
        username: res.data.username,
        email: res.data.email,
        first_name: res.data.first_name,
        last_name: res.data.last_name
      }
      this.editable = !!res.data.editable
      
      // Load theme preference
      const prefs = await api.get('/user/preferences/')
      this.theme = prefs.data.theme || 'dark'
    } catch (e) {
      this.error = e.response?.data?.detail || 'Failed to load user details'
    } finally {
      this.loading = false
    }
  },
  methods: {
    async save() {
      this.loading = true
      try {
        const payload = {
          email: this.user.email,
          first_name: this.user.first_name,
          last_name: this.user.last_name
        }
        const res = await api.patch('/auth/user/', payload)
        this.user = {
          username: res.data.username,
          email: res.data.email,
          first_name: res.data.first_name,
          last_name: res.data.last_name
        }
        this.$q.notify({ type: 'positive', message: 'Profile updated', position: 'top' })
      } catch (e) {
        const msg = e.response?.data?.detail || 'Failed to update profile'
        this.$q.notify({ type: 'negative', message: msg, position: 'top' })
      } finally {
        this.loading = false
      }
    },
    async saveTheme() {
      try {
        await api.patch('/user/preferences/', { theme: this.theme })
        localStorage.setItem('userTheme', this.theme)
        this.$q.dark.set(this.theme === 'dark')
        this.$q.notify({ type: 'positive', message: 'Theme updated', position: 'top' })
      } catch (e) {
        const msg = e.response?.data?.detail || 'Failed to update theme'
        this.$q.notify({ type: 'negative', message: msg, position: 'top' })
      }
    },
    async changePassword() {
      if (!this.editable) return
      if (this.pwd.new1 !== this.pwd.new2) {
        this.$q.notify({ type: 'negative', message: 'New passwords do not match', position: 'top' })
        return
      }
      this.pwdLoading = true
      try {
        await api.post('/auth/change-password/', {
          current_password: this.pwd.current,
          new_password: this.pwd.new1
        })
        this.$q.notify({ type: 'positive', message: 'Password updated', position: 'top' })
        this.pwd = { current: '', new1: '', new2: '' }
      } catch (e) {
        const msg = e.response?.data?.detail || e.response?.data?.current_password || e.response?.data?.new_password || 'Failed to change password'
        this.$q.notify({ type: 'negative', message: msg, position: 'top' })
      } finally {
        this.pwdLoading = false
      }
    }
  }
})
</script>

<style scoped>
</style>
