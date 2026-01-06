<template>
  <q-page class="q-pa-md">
    <q-card>
      <q-card-section>
        <div class="row items-center">
          <div class="col"><div class="text-h6">Users</div></div>
          <div class="col-auto text-caption text-grey">Local and Provisioned</div>
        </div>
      </q-card-section>
      <q-separator />
      <q-card-section>
        <q-table
          :rows="rows"
          :columns="columns"
          row-key="id"
          flat
          :loading="loading"
        >
          <template v-slot:body-cell-actions="props">
            <q-td :props="props">
              <q-btn dense flat icon="visibility" @click="viewUser(props.row)" />
              <q-btn dense flat icon="edit" :disable="props.row.is_jit" @click="editUser(props.row)" />
            </q-td>
          </template>
          <template v-slot:body-cell-name="props">
            <q-td :props="props">
              {{ props.row.first_name }} {{ props.row.last_name }}
            </q-td>
          </template>
          <template v-slot:body-cell-source="props">
            <q-td :props="props">
              <q-badge :color="props.row.is_jit ? 'blue' : 'grey'">{{ props.row.is_jit ? 'Provisioned' : 'Local' }}</q-badge>
            </q-td>
          </template>
        </q-table>
      </q-card-section>
    </q-card>

    <q-dialog v-model="dialog.show">
      <q-card style="min-width: 420px">
        <q-card-section>
          <div class="text-h6">{{ dialog.mode === 'view' ? 'View User' : 'Edit User' }}</div>
          <div class="text-caption text-grey" v-if="dialog.row && dialog.row.is_jit">
            Managed by external identity provider
          </div>
        </q-card-section>
        <q-separator />
        <q-card-section>
          <q-form @submit="saveUser" class="q-gutter-md">
            <q-input v-model="form.username" label="Username" disable />
            <q-input v-model="form.email" label="Email" :disable="dialog.mode==='view' || (dialog.row && dialog.row.is_jit)" />
            <q-input v-model="form.first_name" label="First Name" :disable="dialog.mode==='view' || (dialog.row && dialog.row.is_jit)" />
            <q-input v-model="form.last_name" label="Last Name" :disable="dialog.mode==='view' || (dialog.row && dialog.row.is_jit)" />
            <div class="q-mt-md">
              <q-btn v-if="dialog.mode==='edit' && !(dialog.row && dialog.row.is_jit)" type="submit" color="primary" label="Save" :loading="dialog.loading" />
              <q-btn flat label="Close" class="q-ml-sm" v-close-popup />
            </div>
          </q-form>
        </q-card-section>
      </q-card>
    </q-dialog>
  </q-page>
</template>

<script>
import { defineComponent } from 'vue'
import api from '../services/api'

export default defineComponent({
  name: 'UsersPage',
  data() {
    return {
      loading: false,
      rows: [],
      columns: [
        { name: 'id', label: 'ID', field: 'id', align: 'left' },
        { name: 'username', label: 'Username', field: 'username', align: 'left' },
        { name: 'name', label: 'Name', field: 'name', align: 'left' },
        { name: 'email', label: 'Email', field: 'email', align: 'left' },
        { name: 'source', label: 'Source', field: 'is_jit', align: 'left' },
        { name: 'actions', label: 'Actions', field: 'actions', align: 'right' }
      ],
      dialog: { show: false, mode: 'view', row: null, loading: false },
      form: { username: '', email: '', first_name: '', last_name: '' }
    }
  },
  methods: {
    async fetchUsers() {
      this.loading = true
      try {
        const res = await api.get('/users/')
        this.rows = res.data
      } catch (e) {
        this.$q.notify({ type: 'negative', message: 'Failed to load users', position: 'top' })
      } finally {
        this.loading = false
      }
    },
    viewUser(row) {
      this.dialog.mode = 'view'
      this.dialog.row = row
      this.form = { username: row.username, email: row.email, first_name: row.first_name, last_name: row.last_name }
      this.dialog.show = true
    },
    editUser(row) {
      this.dialog.mode = 'edit'
      this.dialog.row = row
      this.form = { username: row.username, email: row.email, first_name: row.first_name, last_name: row.last_name }
      this.dialog.show = true
    },
    async saveUser() {
      if (!this.dialog.row) return
      this.dialog.loading = true
      try {
        const res = await api.patch(`/users/${this.dialog.row.id}/update_details/`, {
          email: this.form.email,
          first_name: this.form.first_name,
          last_name: this.form.last_name
        })
        // update in rows
        const idx = this.rows.findIndex(r => r.id === this.dialog.row.id)
        if (idx !== -1) this.rows[idx] = res.data
        this.$q.notify({ type: 'positive', message: 'User updated', position: 'top' })
        this.dialog.show = false
      } catch (e) {
        const msg = e.response?.data?.detail || 'Failed to update user'
        this.$q.notify({ type: 'negative', message: msg, position: 'top' })
      } finally {
        this.dialog.loading = false
      }
    }
  },
  mounted() {
    this.fetchUsers()
  }
})
</script>

<style scoped>
</style>
