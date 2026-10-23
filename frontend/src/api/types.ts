// SPDX-License-Identifier: GPL-3.0-or-later
// Shapes of the orchestrator API (see orchestrator/api/serializers.py).

import type { JsonSchema } from '@/utils/schema'

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
  last_run_at: IsoDateTime | null
  /** Null when disabled. */
  next_run: IsoDateTime | null
}

export type JsonObject = Record<string, unknown>

export interface StorageDriver {
  key: string
  name: string
  description: string
  /** Whether several workers can serve one target (a bucket), or only one (a local directory). */
  shareable: boolean
  params_schema: JsonSchema | null
  version: string
  versions: string[]
  /** Approved storage workers offering it. */
  workers: number
}

/** As administrators see it; others get only id, name, description and driver. */
export interface StorageTarget {
  /** UUID. */
  id: string
  name: string
  description: string
  driver: string
  driver_name?: string
  /** Driver settings; secret settings come back as null (see secrets_set). */
  config?: JsonObject
  /** Secret settings that have a stored value. */
  secrets_set?: string[]
  workers?: string[]
  worker_names?: string[]
  queue?: string
  device_count?: number
  job_count?: number
  created_at?: IsoDateTime
  updated_at?: IsoDateTime
}

export interface StorageTargetWrite {
  name: string
  description: string
  driver: string
  config: JsonObject
  workers: string[]
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
  /** JSON schema of the per-device parameters (driver_params), if the driver has any. */
  params_schema: JsonSchema | null
  /** Newest version among approved collectors, and every version they run. */
  version: string
  versions: string[]
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
  driver_params: JsonObject
  collection_group: CollectionGroup | null
  enabled: boolean
  last_backup_time: IsoDateTime | null
  last_backup_status: string | null
  retention_policy: Id | null
  storage_target: string | null
  credential: Id | null
  schedule: Id | null
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
  driver_params: JsonObject
  device_group: Id | null
  collection_group: Id | null
  enabled: boolean
  retention_policy: Id | null
  storage_target: string | null
  credential: Id | null
  schedule: Id | null
}

// --- Backups -------------------------------------------------------------------

/** A backup job's lifecycle; `stored` is the only successful outcome. */
export type JobState = 'queued' | 'collecting' | 'collected' | 'storing' | 'stored' | 'failed' | 'timed_out'

export type JobTrigger = 'manual' | 'schedule'

/** One backup of a device, from request to storage. */
export interface BackupJob {
  /** UUID. */
  id: string
  device: Id
  device_name: string
  state: JobState
  trigger: JobTrigger
  requested_by_username: string | null
  driver: string
  is_binary: boolean
  encrypted: boolean
  size_bytes: number | null
  storage_driver: string
  storage_target: string
  storage_target_name: string | null
  /** Names of the workers that collected and stored it. */
  collector: string
  storage_worker: string
  attempts: number
  error: string
  created_at: IsoDateTime
  started_at: IsoDateTime | null
  collected_at: IsoDateTime | null
  finished_at: IsoDateTime | null
  collect_duration_ms: number | null
  store_duration_ms: number | null
  /** Request to completion. */
  duration_ms: number | null
}

export interface BackupNowResponse {
  job: BackupJob
  /** False if the device already had a backup in progress, which `job` is. */
  created: boolean
}

/** A page of a paginated list endpoint. */
export interface Page<T> {
  count: number
  next: string | null
  previous: string | null
  results: T[]
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
  storage_targets: string[]
  /** SSH-style SHA256 fingerprint of the worker's signing key. */
  fingerprint: string
  capabilities: { collector_drivers?: CollectorDriver[]; storage_drivers?: StorageDriver[] }
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
  storage_targets: string[]
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
  /** Job id; also the key for its logs. */
  id: string
  device_id: Id
  device_name: string
  state: JobState
  trigger: JobTrigger
  created_at: IsoDateTime
  finished_at: IsoDateTime | null
  duration_ms: number | null
  error: string
  has_log: boolean
}

export interface FlowerEndpoint {
  id: Id
  name: string
  /** Proxied at /flower/<slug>/. */
  slug: string
  /** The upstream the web tier proxies to, or the address opened directly. */
  url: string
  proxied: boolean
  /** Where the UI opens it. */
  link: string
  created_at: IsoDateTime
  updated_at: IsoDateTime
}

export type FlowerEndpointWrite = Pick<FlowerEndpoint, 'name' | 'slug' | 'url' | 'proxied'>
