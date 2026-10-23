// SPDX-License-Identifier: GPL-3.0-or-later
// Typed calls to the orchestrator API, one object per resource.

import { http } from './client'
import type {
  ActivityItem,
  ActivityWindow,
  AuthConfig,
  AuthGroup,
  AuthGroupWrite,
  BackupJob,
  BackupMethod,
  BackupNowResponse,
  BackupSchedule,
  CollectionGroup,
  Credential,
  CredentialWrite,
  CredentialType,
  CurrentUser,
  DashboardStats,
  Device,
  DeviceDetail,
  DeviceGroup,
  DeviceGroupRole,
  DeviceType,
  DeviceWrite,
  DjangoPermission,
  Id,
  LogEntry,
  LoginResponse,
  Manufacturer,
  RetentionPolicy,
  StorageDriver,
  StorageTarget,
  StorageTargetWrite,
  ThemeColors,
  User,
  UserCreate,
  UserDetails,
  UserPreferences,
  UserRoleAssignment,
  OrchestratorIdentity,
  Page,
  Worker,
  WorkerAssignment,
} from './types'

type Params = Record<string, string | number | boolean | undefined>

/** A row id: numeric for most resources, a UUID string for some. */
export type Key = Id | string

export interface ResourceApi<T, W> {
  list(params?: Params): Promise<T[]>
  get(id: Key): Promise<T>
  create(body: W): Promise<T>
  update(id: Key, body: W): Promise<T>
  patch(id: Key, body: Partial<W>): Promise<T>
  remove(id: Key): Promise<void>
}

/** CRUD calls for a DRF ModelViewSet at `path` (with trailing slash). */
export function resource<T, W = Omit<T, 'id'>>(path: string): ResourceApi<T, W> {
  return {
    list: async (params) => (await http.get<T[]>(path, { params })).data,
    get: async (id) => (await http.get<T>(`${path}${id}/`)).data,
    create: async (body) => (await http.post<T>(path, body)).data,
    update: async (id, body) => (await http.put<T>(`${path}${id}/`, body)).data,
    patch: async (id, body) => (await http.patch<T>(`${path}${id}/`, body)).data,
    remove: async (id) => {
      await http.delete(`${path}${id}/`)
    },
  }
}

// --- Reference data ------------------------------------------------------------

export const deviceTypesApi = resource<DeviceType>('/device-types/')
export const manufacturersApi = resource<Manufacturer>('/manufacturers/')
export const collectionGroupsApi = resource<
  CollectionGroup,
  Pick<CollectionGroup, 'name' | 'description' | 'rabbitmq_queue_id'>
>('/collection-groups/')
export const retentionPoliciesApi = resource<RetentionPolicy>('/retention-policies/')
export const backupSchedulesApi = resource<
  BackupSchedule,
  Omit<BackupSchedule, 'id' | 'created_at' | 'updated_at' | 'last_run_at' | 'next_run'>
>('/backup-schedules/')
const storageTargets = resource<StorageTarget, StorageTargetWrite>('/storage-targets/')

export const storageTargetsApi = {
  ...storageTargets,
  check: async (id: string) =>
    (await http.post<{ ok: boolean; message?: string; worker?: string; error?: string }>(
      `/storage-targets/${id}/check/`,
    )).data,
}
export const storageDriversApi = {
  list: async () => (await http.get<StorageDriver[]>('/storage-drivers/')).data,
}
export const credentialsApi = resource<Credential, CredentialWrite>('/credentials/')
export const credentialTypesApi = resource<CredentialType>('/credential-types/')
export const deviceGroupsApi = resource<DeviceGroup, Pick<DeviceGroup, 'name' | 'description'>>('/device-groups/')

export const backupMethodsApi = {
  list: async () => (await http.get<BackupMethod[]>('/backup-methods/')).data,
}

// --- Devices and backups ---------------------------------------------------------

const devices = resource<Device, DeviceWrite>('/devices/')

export const devicesApi = {
  list: devices.list,
  remove: devices.remove,
  get: async (id: Id) => (await http.get<DeviceDetail>(`/devices/${id}/`)).data,
  create: async (body: DeviceWrite) => (await http.post<DeviceDetail>('/devices/', body)).data,
  update: async (id: Id, body: DeviceWrite) => (await http.put<DeviceDetail>(`/devices/${id}/`, body)).data,
  backupNow: async (id: Id) => (await http.post<BackupNowResponse>(`/devices/${id}/backup_now/`)).data,
}

export interface JobQuery {
  device?: Id
  state?: string
  page?: number
  page_size?: number
}

export const backupJobsApi = {
  list: async (query: JobQuery) => (await http.get<Page<BackupJob>>('/backups/', { params: query })).data,
  get: async (id: string) => (await http.get<BackupJob>(`/backups/${id}/`)).data,
  contentText: async (id: string) =>
    (await http.get<string>(`/backups/${id}/content/`, { responseType: 'text' })).data,
  contentBlob: async (id: string) =>
    (await http.get<Blob>(`/backups/${id}/content/`, { responseType: 'blob' })).data,
  logs: async (id: string) => (await http.get<{ logs: LogEntry[] }>(`/backups/${id}/logs/`)).data.logs,
}

// --- Users and access ------------------------------------------------------------

const users = resource<User, UserCreate>('/users/')

export const usersApi = {
  list: users.list,
  create: users.create,
  updateDetails: async (id: Id, body: UserDetails) =>
    (await http.patch<User>(`/users/${id}/update_details/`, body)).data,
}

export const groupsApi = resource<AuthGroup, AuthGroupWrite>('/groups/')

export const permissionsApi = {
  list: async () => (await http.get<DjangoPermission[]>('/device-group-permissions/')).data,
}

export const deviceGroupRolesApi = {
  list: async () => (await http.get<DeviceGroupRole[]>('/device-group-roles/')).data,
}

export const userRolesApi = {
  listForUser: async (userId: Id) =>
    (await http.get<UserRoleAssignment[]>('/user-device-group-roles/', { params: { user: userId } })).data,
  assign: async (userId: Id, roleId: Id) =>
    (await http.post<UserRoleAssignment>('/user-device-group-roles/', { user: userId, role: roleId })).data,
  remove: async (assignmentId: Id) => {
    await http.delete(`/user-device-group-roles/${assignmentId}/`)
  },
}

export const authApi = {
  login: async (username: string, password: string) =>
    (await http.post<LoginResponse>('/auth/login/', { username, password })).data,
  logout: async () => {
    await http.post('/auth/logout/')
  },
  currentUser: async () => (await http.get<CurrentUser>('/auth/user/')).data,
  updateCurrentUser: async (body: UserDetails) => (await http.patch<CurrentUser>('/auth/user/', body)).data,
  changePassword: async (currentPassword: string, newPassword: string) => {
    await http.post('/auth/change-password/', { current_password: currentPassword, new_password: newPassword })
  },
  config: async () => (await http.get<AuthConfig>('/auth/config/')).data,
  preferences: async () => (await http.get<UserPreferences>('/user/preferences/')).data,
  updatePreferences: async (body: Partial<UserPreferences>) =>
    (await http.patch<UserPreferences>('/user/preferences/', body)).data,
}

// --- Settings and monitoring -------------------------------------------------------

export const settingsApi = {
  timezone: async () => (await http.get<{ timezone: string }>('/timezone/')).data.timezone,
  theme: async () => (await http.get<ThemeColors>('/theme-settings/')).data,
  updateTheme: async (body: ThemeColors) => (await http.put<ThemeColors>('/theme-settings/', body)).data,
}

export const workersApi = {
  list: async () => (await http.get<Worker[]>('/workers/')).data,
  orchestrator: async () => (await http.get<OrchestratorIdentity>('/workers/orchestrator/')).data,
  approve: async (id: string, body: WorkerAssignment) =>
    (await http.post<Worker>(`/workers/${id}/approve/`, body)).data,
  update: async (id: string, body: Partial<WorkerAssignment> & { name?: string }) =>
    (await http.patch<Worker>(`/workers/${id}/`, body)).data,
  revoke: async (id: string) => (await http.post<Worker>(`/workers/${id}/revoke/`)).data,
  forget: async (id: string) => {
    await http.delete(`/workers/${id}/`)
  },
}

export const dashboardApi = {
  stats: async (days?: number) =>
    (await http.get<DashboardStats>('/dashboard-stats/', { params: days ? { days } : undefined })).data,
  activity: async (window: ActivityWindow) =>
    (await http.get<ActivityItem[]>('/recent-backup-activity/', { params: { time_filter: window } })).data,
}
