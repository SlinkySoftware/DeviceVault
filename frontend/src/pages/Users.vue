<template>
  <q-page class="q-pa-md">
    <q-card>
      <q-card-section>
        <div class="row items-center q-mb-sm">
          <div class="col">
            <div class="text-h5">Users</div>
          </div>
          <div class="col-auto">
            <q-btn 
              v-if="localAuthEnabled" 
              color="primary" 
              label="Add User" 
              icon="person_add"
              @click="showAddUserDialog" 
            />
            <q-btn 
              v-else
              color="grey" 
              label="Add User" 
              icon="person_add"
              disable
            >
              <q-tooltip>
                Local authentication must be enabled to create users. Users can be provisioned through SSO/LDAP instead.
              </q-tooltip>
            </q-btn>
          </div>
        </div>
        <div class="row justify-end">
          <div class="text-caption text-grey">
            Local and Provisioned Users
            <span v-if="!localAuthEnabled" class="text-orange"> • Local auth disabled - only SSO/LDAP users allowed</span>
          </div>
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
          class="admin-table"
        >
          <template v-slot:body-cell-actions="props">
            <q-td :props="props">
              <q-btn color="primary" icon="visibility" label="View" @click="viewUser(props.row)" class="q-mr-sm" />
              <q-btn color="primary" icon="edit" label="Edit" :disable="props.row.is_jit" @click="editUser(props.row)" class="q-mr-sm" />
              <q-btn color="primary" icon="security" label="Roles" @click="manageDeviceGroupRoles(props.row)" class="q-mr-sm" />
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

    <!-- Add User Dialog -->
    <q-dialog v-model="addDialog.show">
      <q-card style="min-width: 420px">
        <q-card-section>
          <div class="text-h6">Add User</div>
          <div class="text-caption text-grey">Create a new local user account</div>
        </q-card-section>
        <q-separator />
        <q-card-section>
          <q-form @submit="createUser" class="q-gutter-md">
            <q-input v-model="addForm.username" label="Username" :rules="[val => !!val || 'Username is required']" />
            <q-input v-model="addForm.email" label="Email" type="email" />
            <q-input v-model="addForm.first_name" label="First Name" />
            <q-input v-model="addForm.last_name" label="Last Name" />
            <q-input 
              v-model="addForm.password" 
              label="Password" 
              type="password"
              :rules="[val => !!val || 'Password is required']"
            />
            <q-input 
              v-model="addForm.password_confirm" 
              label="Confirm Password" 
              type="password"
              :rules="[val => val === addForm.password || 'Passwords do not match']"
            />
            <div class="q-mt-md">
              <q-btn type="submit" color="primary" label="Create User" :loading="addDialog.loading" />
              <q-btn flat label="Cancel" class="q-ml-sm" v-close-popup />
            </div>
          </q-form>
        </q-card-section>
      </q-card>
    </q-dialog>

    <!-- View/Edit User Dialog -->
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

    <!-- Device Group Roles Dialog -->
    <q-dialog v-model="rolesDialog.show">
      <q-card style="min-width: 500px; max-width: 90vw">
        <q-card-section class="row items-center q-pb-none">
          <div class="text-h6">{{ rolesDialog.user?.username }} - Device Group Roles</div>
          <q-space />
          <q-btn icon="close" flat round dense @click="rolesDialog.show = false" />
        </q-card-section>

        <q-separator />

        <q-card-section class="q-gutter-md">
          <!-- Assigned Roles -->
          <div>
            <label class="text-subtitle2 q-mb-md">Assigned Roles</label>
            <div v-if="rolesDialog.assignedRoles && rolesDialog.assignedRoles.length > 0" class="q-mb-md">
              <q-list bordered separator>
                <q-item v-for="assignment in rolesDialog.assignedRoles" :key="assignment.id">
                  <q-item-section>
                    <q-item-label>{{ assignment.role?.name }}</q-item-label>
                    <q-item-label caption>{{ assignment.role?.device_group_name }}</q-item-label>
                  </q-item-section>
                  <q-item-section side>
                    <q-btn
                      flat
                      dense
                      color="negative"
                      icon="delete"
                      size="sm"
                      @click="removeRoleFromUser(assignment.id)"
                    />
                  </q-item-section>
                </q-item>
              </q-list>
            </div>
            <div v-else class="text-grey-6 italic q-mb-md">
              No roles assigned
            </div>
          </div>

          <!-- Add Role -->
          <div>
            <label class="text-subtitle2 q-mb-md">Add Role</label>
            <q-select
              v-model="rolesDialog.selectedRole"
              :options="rolesDialog.availableRoles"
              option-value="id"
              option-label="name"
              outlined
              dense
              @update:model-value="rolesDialog.selectedRole = $event"
            >
              <template #option="scope">
                <q-item v-bind="scope.itemProps">
                  <q-item-section>
                    <q-item-label>{{ scope.opt.name }}</q-item-label>
                    <q-item-label caption>{{ scope.opt.device_group_name }}</q-item-label>
                  </q-item-section>
                </q-item>
              </template>
            </q-select>
            <q-btn
              label="Assign Role"
              color="primary"
              class="q-mt-md"
              :disable="!rolesDialog.selectedRole"
              @click="assignRoleToUser"
              :loading="rolesDialog.loading"
            />
          </div>
        </q-card-section>

        <q-card-section class="row items-center justify-end q-gutter-sm q-pt-none">
          <q-btn
            label="Close"
            color="primary"
            flat
            @click="rolesDialog.show = false"
          />
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
      localAuthEnabled: false,
      rows: [],
      columns: [
        { name: 'id', label: 'ID', field: 'id', align: 'left' },
        { name: 'username', label: 'Username', field: 'username', align: 'left' },
        { name: 'name', label: 'Name', field: 'name', align: 'left' },
        { name: 'email', label: 'Email', field: 'email', align: 'left' },
        { name: 'source', label: 'Source', field: 'is_jit', align: 'left' },
        { name: 'actions', label: 'Actions', field: 'actions', align: 'right' }
      ],
      addDialog: { show: false, loading: false },
      addForm: { username: '', email: '', first_name: '', last_name: '', password: '', password_confirm: '' },
      dialog: { show: false, mode: 'view', row: null, loading: false },
      form: { username: '', email: '', first_name: '', last_name: '' },
      rolesDialog: {
        show: false,
        user: null,
        loading: false,
        assignedRoles: [],
        availableRoles: [],
        selectedRole: null
      }
    }
  },
  methods: {
    async fetchAuthConfig() {
      try {
        const res = await api.get('/api/auth/config/')
        this.localAuthEnabled = res.data.local_enabled || res.data.auth_type === 'Local'
      } catch (e) {
        console.error('Failed to load auth config:', e)
      }
    },

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

    showAddUserDialog() {
      this.addForm = { username: '', email: '', first_name: '', last_name: '', password: '', password_confirm: '' }
      this.addDialog.show = true
    },

    async createUser() {
      if (this.addForm.password !== this.addForm.password_confirm) {
        this.$q.notify({ type: 'negative', message: 'Passwords do not match', position: 'top' })
        return
      }

      this.addDialog.loading = true
      try {
        const payload = {
          username: this.addForm.username,
          email: this.addForm.email,
          first_name: this.addForm.first_name,
          last_name: this.addForm.last_name,
          password: this.addForm.password
        }
        const res = await api.post('/users/', payload)
        this.rows.push(res.data)
        this.$q.notify({ type: 'positive', message: 'User created successfully', position: 'top' })
        this.addDialog.show = false
      } catch (e) {
        const msg = e.response?.data?.detail || 'Failed to create user'
        this.$q.notify({ type: 'negative', message: msg, position: 'top' })
      } finally {
        this.addDialog.loading = false
      }
    },

    async fetchDeviceGroupRoles() {
      try {
        const res = await api.get('/device-group-roles/')
        this.rolesDialog.availableRoles = res.data
      } catch (e) {
        this.$q.notify({ type: 'negative', message: 'Failed to load roles', position: 'top' })
      }
    },

    async loadUserRoles() {
      try {
        const res = await api.get('/user-device-group-roles/', {
          params: { user: this.rolesDialog.user.id }
        })
        this.rolesDialog.assignedRoles = res.data
      } catch (e) {
        console.error('Failed to load user roles:', e)
        this.rolesDialog.assignedRoles = []
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
    },

    async manageDeviceGroupRoles(user) {
      this.rolesDialog.user = user
      this.rolesDialog.selectedRole = null
      this.rolesDialog.assignedRoles = []
      this.rolesDialog.show = true
      
      await Promise.all([
        this.fetchDeviceGroupRoles(),
        this.loadUserRoles()
      ])
    },

    async assignRoleToUser() {
      if (!this.rolesDialog.selectedRole || !this.rolesDialog.user) return
      
      this.rolesDialog.loading = true
      try {
        await api.post('/user-device-group-roles/', {
          user: this.rolesDialog.user.id,
          role: this.rolesDialog.selectedRole
        })
        this.$q.notify({ type: 'positive', message: 'Role assigned', position: 'top' })
        this.rolesDialog.selectedRole = null
        await this.loadUserRoles()
      } catch (e) {
        const msg = e.response?.data?.detail || 'Failed to assign role'
        this.$q.notify({ type: 'negative', message: msg, position: 'top' })
      } finally {
        this.rolesDialog.loading = false
      }
    },

    async removeRoleFromUser(assignmentId) {
      this.rolesDialog.loading = true
      try {
        await api.delete(`/user-device-group-roles/${assignmentId}/`)
        this.$q.notify({ type: 'positive', message: 'Role removed', position: 'top' })
        await this.loadUserRoles()
      } catch (e) {
        const msg = e.response?.data?.detail || 'Failed to remove role'
        this.$q.notify({ type: 'negative', message: msg, position: 'top' })
      } finally {
        this.rolesDialog.loading = false
      }
    }
  },
  mounted() {
    this.fetchAuthConfig()
    this.fetchUsers()
  }
})
</script>
