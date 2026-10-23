// SPDX-License-Identifier: GPL-3.0-or-later
// Shapes of the orchestrator API (see orchestrator/api/serializers.py).

export type Id = number
export type IsoDateTime = string

// --- Reference data ---------------------------------------------------------

export interface DeviceType {
  id: Id
  name: string
  icon: string
}

export interface Manufacturer {
  id: Id
  name: string
}

export interface CollectionGroup {
  id: Id
  name: string
  description: string
  rabbitmq_queue_id: string
  device_count: number
  /** Approved collectors consuming this group's queue. */
  collector_count: number
  created_at: IsoDateTime
  updated_at: IsoDateTime
}

export interface RetentionPolicy {
  id: Id
  name: string
  max_backups: number | null
  max_days: number | null
  max_size_bytes: number | null
}

export type ScheduleType = 'daily' | 'weekly' | 'monthly' | 'custom_cron'

export interface BackupSchedule {
  id: Id
  name: string
  description: string
  schedule_type: ScheduleType
  hour: number
  minute: number
  /** 0 = Sunday ... 6 = Saturday */
  day_of_week: string
  day_of_month: number
  cron_expression: string
  enabled: boolean
  created_at: IsoDateTime
  updated_at: IsoDateTime
}

export type JsonObject = Record<string, unknown>

export interface BackupLocation {
  id: Id
  name: string
  location_type: string
  /** Only returned to administrators. */
  config?: JsonObject
}

export interface BackupLocationWrite {
  name: string
  location_type: string
  config: JsonObject
}

export interface CredentialType {
  id: Id
  name: string
}

export interface Credential {
  id: Id
  name: string
  credential_type: Id
  /** Only returned to administrators. */
  data?: JsonObject
}

export interface CredentialWrite {
  name: string
  credential_type: Id | null
  data: JsonObject
}

export interface BackupMethod {
  key: string
  friendly_name: string
  description: string
  is_binary: boolean
  /** Approved collectors offering this method. */
  collectors: number
}

// --- Devices -----------------------------------------------------------------

export type DevicePermission = 'view' | 'modify' | 'view_backups' | 'backup_now'

export interface DeviceGroup {
  id: Id
  name: string
  description: string
  roles: DeviceGroupRole[]
  created_at: IsoDateTime
  updated_at: IsoDateTime
  can_modify: boolean
  user_permissions: DevicePermission[]
}

interface DeviceBase {
  id: Id
  name: string
  ip_address: string
  dns_name: string
  device_type: DeviceType
  manufacturer: Manufacturer | null
  backup_method: string
  backup_method_display: string
  collection_group: CollectionGroup | null
  enabled: boolean
  encrypt_backups: boolean
  last_backup_time: IsoDateTime | null
  last_backup_status: string | null
  retention_policy: Id | null
  backup_location: Id | null
  credential: Id | null
  user_permissions: DevicePermission[]
}

/** List representation. */
export interface Device extends DeviceBase {
  device_group: Id | null
  device_group_name: string | null
}

/** Retrieve / create / update representation. */
export interface DeviceDetail extends DeviceBase {
  device_group: DeviceGroup | null
}

export interface DeviceWrite {
  name: string
  ip_address: string
  dns_name: string
  device_type: Id | null
  manufacturer: Id | null
  backup_method: string
  device_group: Id | null
  collection_group: Id | null
  enabled: boolean
  encrypt_backups: boolean
  retention_policy: Id | null
  backup_location: Id | null
  credential: Id | null
}

export interface DispatchResponse {
  task_id: string
  queued_on: string
}

// --- Backups -------------------------------------------------------------------

export type BackupStatus = 'success' | 'failure'

export interface StoredBackup {
  id: Id
  device: Id
  timestamp: IsoDateTime
  task_identifier: string
  backup_status: string
  storage_status: string | null
  storage_backend: string | null
  storage_ref: string | null
  storage_timestamp: IsoDateTime | null
  /** Overall status: success only if both collection and storage succeeded. */
  status: BackupStatus
  is_text: boolean
  is_encrypted: boolean
  enc_kid: string | null
}

export type LogSeverity = 'DEBUG' | 'INFO' | 'WARN' | 'WARNING' | 'ERROR'

export interface LogEntry {
  source: string
  timestamp: IsoDateTime
  severity: LogSeverity | string
  message: string
}

// --- Users and access ------------------------------------------------------

export interface User {
  id: Id
  username: string
  email: string
  first_name: string
  last_name: string
  is_staff: boolean
  is_superuser: boolean
  is_jit: boolean
}

export interface CurrentUser extends User {
  /** False for users managed by an external identity provider. */
  editable: boolean
  is_admin: boolean
}

export interface UserCreate {
  username: string
  email: string
  first_name: string
  last_name: string
  password: string
}

export type UserDetails = Pick<User, 'email' | 'first_name' | 'last_name'>

export interface DjangoPermission {
  id: Id
  codename: string
  name: string
}

export interface AuthGroup {
  id: Id
  name: string
  users: Pick<User, 'id' | 'username' | 'email'>[]
  device_group_permissions: DjangoPermission[]
}

export interface AuthGroupWrite {
  name: string
  user_ids: Id[]
  permission_ids: Id[]
}

export interface DeviceGroupRole {
  id: Id
  name: string
  device_group: Id
  device_group_name: string
  permissions: Id[]
  created_at: IsoDateTime | null
}

export interface UserRoleAssignment {
  id: Id
  user: Id
  username: string
  role: DeviceGroupRole
}

export interface AuthConfig {
  providers: string[]
  local_enabled: boolean
  auth_type: string | null
}

export interface LoginResponse {
  token: string
  user: User
}

// --- Settings ----------------------------------------------------------------

export type ThemeMode = 'dark' | 'light'

export interface ThemeColors {
  title_bar_color: string
  dashboard_box_color: string
  dashboard_nested_box_color: string
}

export interface UserPreferences {
  theme: ThemeMode
}

// --- Monitoring --------------------------------------------------------------

export type WorkerStatus = 'pending' | 'approved' | 'revoked'
export type WorkerRole = 'collector' | 'storage'

export interface CollectorDriver {
  key: string
  name: string
  description: string
  is_binary: boolean
}

export interface Worker {
  id: string
  name: string
  celery_hostname: string
  hostname: string
  pid: number | null
  version: string
  status: WorkerStatus
  role: WorkerRole | ''
  collection_groups: Id[]
  storage_backends: string[]
  /** SSH-style SHA256 fingerprint of the worker's signing key. */
  fingerprint: string
  capabilities: { collector_drivers?: CollectorDriver[]; storage_backends?: string[] }
  desired_version: number
  applied_version: number
  applied_queues: string[]
  assigned_queues: string[]
  in_sync: boolean
  /** Whether the key the worker pinned is this orchestrator's; null until it pins one. */
  pinned_orchestrator_matches: boolean | null
  registered_at: IsoDateTime
  approved_at: IsoDateTime | null
  approved_by_username: string | null
  last_seen_at: IsoDateTime | null
  is_online: boolean
}

export interface WorkerAssignment {
  role: WorkerRole
  collection_groups: Id[]
  storage_backends: string[]
}

export interface OrchestratorIdentity {
  fingerprint: string
  online_timeout_seconds: number
}

export interface DailyStat {
  /** Calendar date in the display timezone, `YYYY-MM-DD`. */
  date: string
  success: number
  failed: number
  /** Success rate, 0-100. */
  rate: number
}

export interface DashboardStats {
  devicesByType: Record<string, { count: number; icon: string | null }>
  success24h: number
  failed24h: number
  inProgress24h: number
  /** Seconds. */
  avgDuration: number
  successRate: number
  dailyStats: DailyStat[]
  timezone: string
}

export type ActivityWindow = '1h' | '24h' | '7d'

export interface ActivityItem {
  /** Backup result id; also the key for its logs. */
  id: Id
  task_identifier: string
  device_name: string
  device_type: string
  timestamp: IsoDateTime | null
  status: string
  status_display: string
  storage_status: string
  storage_status_display: string
  duration: number | null
  log: string | null
}
