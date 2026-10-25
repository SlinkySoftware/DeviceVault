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

/** What the last retention pass of a policy found and did. */
export interface RetentionResult {
  dry_run: boolean
  /** Expired backups retention can delete. */
  expired: number
  expired_bytes: number
  /** Expired, but on a target whose driver keeps everything (git). */
  kept_undeletable: number
  /** Deletions sent to storage workers (0 in a dry run). */
  requested: number
}

/** Any limit that is set applies; the newest `min_backups` and pinned backups are always kept. */
export interface RetentionPolicy {
  id: Id
  name: string
  max_backups: number | null
  max_days: number | null
  max_size_bytes: number | null
  min_backups: number
  /** Only report what would be deleted. */
  dry_run: boolean
  last_run_at: IsoDateTime | null
  /** Empty until the first pass. */
  last_result: Partial<RetentionResult>
}

export type RetentionPolicyWrite = Omit<RetentionPolicy, 'id' | 'last_run_at' | 'last_result'>

/** What a policy expires now, by device. */
export interface RetentionPreview {
  expired: number
  expired_bytes: number
  kept_undeletable: number
  devices: {
    device: Id
    device_name: string
    backups: number
    bytes: number
    oldest: IsoDateTime
    newest: IsoDateTime
  }[]
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
  /** Whether retention can delete its backups (git keeps its history). */
  deletes: boolean
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

/** A credential; its data is write-only, so only the names of the keys that are set come back. */
export interface Credential {
  id: Id
  name: string
  credential_type: Id
  /** Owning device group; null for a global credential. */
  device_group: Id | null
  device_group_name: string | null
  data_keys: string[]
}

export interface CredentialWrite {
  name: string
  credential_type: Id | null
  device_group: Id | null
  /** On update, a key sent as null keeps its stored value; omit data to keep it all. */
  data?: JsonObject
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

/** Permissions on a device group, weakest first (see accounts/models.py). */
export type GrantFlag = 'view' | 'backup_now' | 'view_contents' | 'download' | 'admin'

export interface DeviceGroup {
  id: Id
  name: string
  description: string
  device_count: number
  created_at: IsoDateTime
  updated_at: IsoDateTime
  /** What the signed-in user holds on this group. */
  user_permissions: GrantFlag[]
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
  push_mode: PushMode
  push_filename_pattern: string
  last_backup_time: IsoDateTime | null
  last_backup_status: string | null
  retention_policy: Id | null
  storage_target: string | null
  credential: Id | null
  schedule: Id | null
  /** What the signed-in user holds on this device's group. */
  user_permissions: GrantFlag[]
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
  /** Empty: not polled (only for devices that push). */
  backup_method: string
  driver_params: JsonObject
  device_group: Id | null
  collection_group: Id | null
  enabled: boolean
  push_mode: PushMode
  push_filename_pattern: string
  retention_policy: Id | null
  storage_target: string | null
  credential: Id | null
  schedule: Id | null
}

// --- Backups -------------------------------------------------------------------

/** A backup job's lifecycle; `stored` is the only successful outcome. */
export type JobState = 'queued' | 'collecting' | 'collected' | 'storing' | 'stored' | 'failed' | 'timed_out'

export type JobTrigger = 'manual' | 'schedule' | 'push'

/** One backup of a device, from request to storage. */
export interface BackupJob {
  /** UUID. */
  id: string
  device: Id
  device_name: string
  state: JobState
  trigger: JobTrigger
  requested_by_username: string | null
  /** Collector driver key, or `push:<protocol>` for a pushed backup. */
  driver: string
  /** Name the device pushed the file as (pushed backups only). */
  source_filename: string
  is_binary: boolean
  encrypted: boolean
  size_bytes: number | null
  storage_driver: string
  storage_target: string
  storage_target_name: string | null
  /** Names of the workers that collected and stored it. */
  collector: string
  storage_worker: string
  /** Exempt from retention. */
  pinned: boolean
  /** Deleted (or being deleted) by retention: the content is gone. */
  pruned: boolean
  pruned_at: IsoDateTime | null
  /** Change summary against `compared_to` (the previous backup): null until made, or if it could not be. */
  changed: boolean | null
  /** Null for binary backups. */
  lines_added: number | null
  lines_removed: number | null
  /** The previous backup; null for the device's first. */
  compared_to: string | null
  /** Why there is no summary. */
  summary_error: string
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

export interface ComparedBackup {
  job: BackupJob
  content: string
}

export interface BackupComparison {
  a: ComparedBackup
  b: ComparedBackup
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

export type UserSource = 'local' | 'external'

export interface User {
  id: Id
  username: string
  email: string
  first_name: string
  last_name: string
  is_active: boolean
  source: UserSource
  /** Names of the identity providers the user signs in with. */
  providers: string[]
  /** User groups (ids) the user is a member of. */
  groups: Id[]
  group_names: string[]
  is_global_admin: boolean
  /** A local user who may sign in even when local authentication is disabled. */
  break_glass: boolean
  last_login: IsoDateTime | null
  date_joined: IsoDateTime
}

export interface UserCreate {
  username: string
  email: string
  first_name: string
  last_name: string
  password: string
  is_active: boolean
  groups: Id[]
  break_glass: boolean
}

export type UserUpdate = Pick<User, 'email' | 'first_name' | 'last_name' | 'is_active' | 'groups' | 'break_glass'>

export type UserDetails = Pick<User, 'email' | 'first_name' | 'last_name'>

/** The signed-in user and their effective permissions. */
export interface CurrentUser {
  id: Id
  username: string
  email: string
  first_name: string
  last_name: string
  source: UserSource
  providers: string[]
  /** False for users managed by an external identity provider. */
  editable: boolean
  is_global_admin: boolean
  /** Device group id -> flags held on it. */
  grants: Record<string, GrantFlag[]>
}

export type GrantFlags = Record<GrantFlag, boolean>

export interface Grant extends GrantFlags {
  device_group: Id
  device_group_name?: string
}

export interface UserGroup {
  id: Id
  name: string
  description: string
  is_global_admin: boolean
  /** The built-in Administrators group: cannot be deleted or lose its flag. */
  is_builtin: boolean
  source: 'internal' | 'external'
  /** External groups: the provider that fills them, and its name for the group. */
  provider_name: string | null
  external_id: string
  members: Id[]
  member_names: string[]
  grants: Grant[]
  created_at: IsoDateTime
  updated_at: IsoDateTime
}

export type UserGroupWrite = Pick<UserGroup, 'name' | 'description' | 'is_global_admin' | 'members' | 'grants'>

export type AuditOutcome = 'success' | 'failure' | 'denied'

export interface AuditEntry {
  id: Id
  created_at: IsoDateTime
  actor: Id | null
  actor_name: string
  action: string
  resource: string
  outcome: AuditOutcome
  details: JsonObject
  ip: string | null
  user_agent: string
  device_group: Id | null
  device_group_name: string | null
}

/** Filters of the audit log; `action` is a prefix such as `auth.`. */
export interface AuditQuery {
  page?: number | undefined
  page_size?: number | undefined
  action?: string | undefined
  outcome?: AuditOutcome | undefined
  actor?: string | undefined
  search?: string | undefined
  device_group?: Id | undefined
  since?: string | undefined
  until?: string | undefined
}

export interface LoginProvider {
  slug: string
  name: string
  kind: string
  /** Signs in with the login form (LDAP) rather than a redirect (OIDC). */
  password_login: boolean
}

export interface AuthConfig {
  providers: LoginProvider[]
  local_enabled: boolean
}

export interface AuthProviderKind {
  key: string
  name: string
  password_login: boolean
  params_schema: JsonSchema | null
}

export interface MappingRule {
  external_group: string
  user_group: Id
  user_group_name?: string
}

export interface AuthProvider {
  id: Id
  slug: string
  name: string
  kind: string
  kind_name: string
  enabled: boolean
  order: number
  /** Settings; secret settings come back as null (see secrets_set). */
  config: JsonObject
  secrets_set: string[]
  auto_create_users: boolean
  auto_create_groups: boolean
  /** If set, only members of this provider group may sign in. */
  login_group: string
  mapping_rules: MappingRule[]
  user_count: number
  /** Where the IdP sends users back (redirect providers only). */
  redirect_uri?: string
  created_at: IsoDateTime
  updated_at: IsoDateTime
}

export type AuthProviderWrite = Pick<
  AuthProvider,
  | 'slug'
  | 'name'
  | 'kind'
  | 'enabled'
  | 'order'
  | 'config'
  | 'auto_create_users'
  | 'auto_create_groups'
  | 'login_group'
  | 'mapping_rules'
>

export interface ProviderTestResult {
  ok: boolean
  error?: string
  server?: string
  bound_as?: string
  /** With a username: what the provider says about that user (null: not found). */
  user?: { dn?: string; subject: string; username: string; email: string; name: string; groups: string[] } | null
  [key: string]: unknown
}

export interface LoginResponse {
  user: CurrentUser
}

// --- Settings ----------------------------------------------------------------

export type ThemeMode = 'dark' | 'light'

export interface UserPreferences {
  theme: ThemeMode
}

// --- Monitoring --------------------------------------------------------------

export type WorkerStatus = 'pending' | 'approved' | 'revoked'
export type WorkerRole = 'collector' | 'storage' | 'receiver'

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
  capabilities: {
    collector_drivers?: CollectorDriver[]
    storage_drivers?: StorageDriver[]
    /** Present on push receivers only. */
    receiver?: { protocols: PushProtocol[]; host_key_fingerprint: string }
  }
  desired_version: number
  applied_version: number
  applied_queues: string[]
  assigned_queues: string[]
  /** What the worker reports about its services (receivers: listeners, host key). */
  runtime: { receiver?: ReceiverRuntime }
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

// --- Push collection -----------------------------------------------------------------

/** How a device uploads its own backups to the receivers. */
export type PushMode = 'off' | 'ssh' | 'tftp'
export type PushProtocol = 'ssh' | 'tftp'

export interface ListenerStatus {
  enabled: boolean
  port: number
  listening: boolean
  error: string
}

/** What a receiver reports in its heartbeats. */
export interface ReceiverRuntime {
  /** OpenSSH-style SHA256 fingerprint of its SSH host key. */
  host_key_fingerprint: string
  vault_kid: string | null
  /** Push-enabled devices it accepts. */
  devices: number
  listeners: { ssh?: ListenerStatus; tftp?: ListenerStatus }
}

/** One receiver's settings; the password is write-only. */
export interface ReceiverSettings {
  /** Empty or null: every address. */
  bind_address: string | null
  max_file_size: number
  ssh_enabled: boolean
  ssh_port: number
  ssh_username: string
  ssh_password_set: boolean
  ssh_authorized_keys: string
  tftp_enabled: boolean
  tftp_port: number
  updated_at: IsoDateTime
}

export interface ReceiverSettingsWrite {
  bind_address: string | null
  max_file_size: number
  ssh_enabled: boolean
  ssh_port: number
  ssh_username: string
  /** Omit to keep the current password; empty removes it. */
  ssh_password?: string
  ssh_authorized_keys: string
  tftp_enabled: boolean
  tftp_port: number
}

export type PushRejectionReason =
  | 'unknown_source'
  | 'auth_failed'
  | 'wrong_protocol'
  | 'filename'
  | 'too_large'
  | 'device_changed'
  | 'error'

/** A push a receiver refused, or the orchestrator discarded. */
export interface PushRejection {
  id: Id
  at: IsoDateTime
  source_ip: string
  protocol: PushProtocol
  reason: PushRejectionReason
  filename: string
  detail: string
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
