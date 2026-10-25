// SPDX-License-Identifier: GPL-3.0-or-later
// Typed calls to the orchestrator API, one object per resource.

import { http } from './client'
import type {
  ActivityItem,
  ActivityWindow,
  AuditEntry,
  AuditQuery,
  AuthConfig,
  AuthProvider,
  AuthProviderKind,
  AuthProviderWrite,
  BackupComparison,
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
  DeviceType,
  DeviceWrite,
  FlowerEndpoint,
  FlowerEndpointWrite,
  Id,
  LogEntry,
  LoginResponse,
  Manufacturer,
  RetentionPolicy,
  RetentionPolicyWrite,
  RetentionPreview,
  SavedSearch,
  SavedSearchWrite,
  SearchQuery,
  SearchResponse,
  StorageDriver,
  StorageTarget,
  StorageTargetWrite,
  User,
  UserCreate,
  UserDetails,
  UserGroup,
  UserGroupWrite,
  UserPreferences,
  UserUpdate,
  OrchestratorIdentity,
  Page,
  PushRejection,
  ReceiverSettings,
  ReceiverSettingsWrite,
  ProviderTestResult,
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
const retentionPolicies = resource<RetentionPolicy, RetentionPolicyWrite>('/retention-policies/')

export const retentionPoliciesApi = {
  ...retentionPolicies,
  /** What the policy expires now (global administrators). */
  preview: async (id: Id) => (await http.get<RetentionPreview>(`/retention-policies/${id}/preview/`)).data,
}

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

const flowerEndpoints = resource<FlowerEndpoint, FlowerEndpointWrite>('/flower-endpoints/')

export const flowerEndpointsApi = {
  ...flowerEndpoints,
  /** Sets the cookie that lets this browser open a proxied endpoint (for a few hours). */
  session: async (id: Id) => (await http.post<{ link: string }>(`/flower-endpoints/${id}/session/`)).data,
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
  /** Only backups that changed (true) or did not (false). */
  changed?: boolean
  page?: number
  page_size?: number
}

export const backupJobsApi = {
  list: async (query: JobQuery) => (await http.get<Page<BackupJob>>('/backups/', { params: query })).data,
  get: async (id: string) => (await http.get<BackupJob>(`/backups/${id}/`)).data,
  /** Needs view_contents on the device's group. */
  contentText: async (id: string) =>
    (await http.get<string>(`/backups/${id}/content/`, { responseType: 'text' })).data,
  /** Needs download on the device's group. */
  download: async (id: string) =>
    (await http.get<Blob>(`/backups/${id}/download/`, { responseType: 'blob' })).data,
  /** Two text backups of one device; needs view_contents. */
  compare: async (a: string, b: string) =>
    (await http.get<BackupComparison>('/backups/compare/', { params: { a, b } })).data,
  logs: async (id: string) => (await http.get<{ logs: LogEntry[] }>(`/backups/${id}/logs/`)).data.logs,
}

// --- Config search ---------------------------------------------------------------

export const searchApi = {
  /** The latest backups of devices the user may read (needs view_contents). A POST: queries may hold secrets. */
  search: async (query: SearchQuery) => (await http.post<SearchResponse>('/search/', query)).data,
}

/** The signed-in user's own saved searches. */
export const savedSearchesApi = resource<SavedSearch, SavedSearchWrite>('/saved-searches/')

// --- Users and access ------------------------------------------------------------

const users = resource<User, UserCreate>('/users/')

export const usersApi = {
  list: users.list,
  create: users.create,
  remove: users.remove,
  update: async (id: Id, body: Partial<UserUpdate>) => (await http.patch<User>(`/users/${id}/`, body)).data,
  setPassword: async (id: Id, password: string) => {
    await http.post(`/users/${id}/set_password/`, { password })
  },
}

const userGroups = resource<UserGroup, UserGroupWrite>('/user-groups/')

// Groups are edited with PATCH, so members and grants are replaced explicitly.
export const userGroupsApi = { ...userGroups, update: (id: Key, body: UserGroupWrite) => userGroups.patch(id, body) }

const authProviders = resource<AuthProvider, AuthProviderWrite>('/auth-providers/')

export const authProvidersApi = {
  ...authProviders,
  update: (id: Key, body: AuthProviderWrite) => authProviders.patch(id, body),
  test: async (id: Id, username: string) =>
    (await http.post<ProviderTestResult>(`/auth-providers/${id}/test/`, { username })).data,
}

export const authProviderKindsApi = {
  list: async () => (await http.get<AuthProviderKind[]>('/auth-provider-kinds/')).data,
}

export const auditLogApi = {
  list: async (query: AuditQuery) => (await http.get<Page<AuditEntry>>('/audit-logs/', { params: query })).data,
}

/** Where the browser goes to sign in with a redirect provider (OIDC); it comes back to `next`. */
export const oidcLoginUrl = (slug: string, next: string) =>
  `/api/auth/oidc/${encodeURIComponent(slug)}/login/?${new URLSearchParams({ next }).toString()}`

export const authApi = {
  /** Sets the CSRF cookie that unsafe requests echo. */
  csrf: async () => {
    await http.get('/auth/csrf/')
  },
  login: async (username: string, password: string) =>
    (await http.post<LoginResponse>('/auth/login/', { username, password })).data,
  /** Ends the session; an OIDC session may name the IdP's end-session URL to visit next. */
  logout: async () => (await http.post<{ redirect?: string } | ''>('/auth/logout/')).data || {},
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
  version: async () => (await http.get<{ version: string }>('/version/')).data.version,
}

export const workersApi = {
  list: async () => (await http.get<Worker[]>('/workers/')).data,
  orchestrator: async () => (await http.get<OrchestratorIdentity>('/workers/orchestrator/')).data,
  approve: async (id: string, body: WorkerAssignment) =>
    (await http.post<Worker>(`/workers/${id}/approve/`, body)).data,
  update: async (id: string, body: Partial<WorkerAssignment> & { name?: string }) =>
    (await http.patch<Worker>(`/workers/${id}/`, body)).data,
  revoke: async (id: string) => (await http.post<Worker>(`/workers/${id}/revoke/`)).data,
  receiverSettings: async (id: string) => (await http.get<ReceiverSettings>(`/workers/${id}/receiver/`)).data,
  updateReceiverSettings: async (id: string, body: ReceiverSettingsWrite) =>
    (await http.patch<ReceiverSettings>(`/workers/${id}/receiver/`, body)).data,
  rejections: async (id: string) => (await http.get<PushRejection[]>(`/workers/${id}/rejections/`)).data,
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
