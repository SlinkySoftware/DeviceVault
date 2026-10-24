# DeviceVault — Target Architecture & Delivery Plan

Status: **Agreed** (2026-10-23). Decisions on the former open questions are recorded in section 11. Phases 8-10 (authentication, authorization and audit, section 4.4) were added on 2026-10-24; phases 8-10 are implemented. Push collection (unsolicited SCP, SFTP and TFTP uploads, section 7.1, phases 11-13) was added on 2026-10-24; phases 11-13 are implemented.

## 1. Goals

1. Hard separation between the **infra layer** (DB, RabbitMQ, Redis), the **orchestrator**, and **workers**. Each deploys independently.
2. Workers hold **no configuration** beyond the RabbitMQ and Redis endpoints (plus TLS CA). They register, wait for admin approval, and receive their role, queues, and config from the orchestrator.
3. Storage is configured **per storage target**, assigned to specific workers, not per storage type.
4. The UI stores Flower endpoints and gives admins direct access to them.
5. Collector drivers and storage drivers are pluggable. New device platforms and storage backends (including an arbitrary database) are additive, not invasive.
6. Current stacks: Python 3.14 (verified: Django 6.1.2, Celery 5.6.3, psycopg 3, djangosaml2/xmlsec, python-ldap, netmiko, scrapli, flower all install and run), Node 24, Quasar 2.35 / Vue 3.5 / vue-router 5 / Pinia 4. Docker is the only deployment target.

Sizing assumptions: 6–8 collectors, 2–4 storage workers, a few receivers, backups from hundreds of KB up to tens of MB; pushed files up to 512 MiB.

## 2. Components

```
                     ┌──────────── infra (deploy/infra) ────────────┐
                     │  PostgreSQL | SQLite(vol)   RabbitMQ   Redis │
                     └───────▲───────────────▲──────────▲───────────┘
                             │               │          │
  ┌─ orchestrator node(s) (deploy/orchestrator) ─┐      │
  │ web       nginx + SPA + /flower proxy        │      │
  │ api       Django/DRF (gunicorn)              │      │
  │ events    Celery worker, queue dv.orchestrator (Django)
  │ scheduler leader-elected loop (Django)       │      │
  │ flower    optional                           │      │
  └──────────────────────────────────────────────┘      │
                             │ AMQP + Redis only        │
  ┌─ worker (deploy/worker) — one image, no Django ─────┴──┐
  │ role=collector: consumes collector.group.<id>          │
  │ role=storage:   consumes storage.target.<uuid>         │
  │ always:         dv.worker.<worker_id> (control/direct) │
  └────────────────────────────────────────────────────────┘
                             │ AMQP + Redis only
  ┌─ receiver (deploy/receiver) — own image, host network ─┐
  │ role=receiver: SCP/SFTP and TFTP listeners             │◄── devices push
  │ always:         dv.worker.<worker_id>.control          │
  └────────────────────────────────────────────────────────┘
```

No component talks to another directly. Everything goes over AMQP or Redis. The one exception is inbound: devices push files to a receiver (section 7.1).

### Orchestrator processes (same image, different commands)

| Process | Scaling | Responsibility |
|---|---|---|
| `api` | active/active | REST API, auth, RBAC |
| `web` | active/active | nginx serving the built SPA, `/api` → api, `/flower/<id>/` → Flower (via `auth_request`) |
| `events` | active/active (competing consumers) | Celery worker on `dv.orchestrator`. Handles `worker.register`, `job.collected`, `job.stored`, `job.failed`. Replaces `consume_device_results`, `consume_storage_results`, and `monitor_worker_registry`. |
| `scheduler` | runs everywhere, **one leader** (Redis lock with TTL and renewal) | Reads `BackupSchedule` from the DB and dispatches due jobs. Sends liveness pings, times out stale jobs, and (later) triggers retention. Replaces celery beat, whose local schedule file isn't HA-safe. |

Both are in place since phase 5: `events` handles worker registration, heartbeats and the signed job events (`orchestrator.job_event`: started, retrying, collected, stored, failed); `scheduler` holds the Redis lease `dv:scheduler:leader` (60 s or twice the tick interval, renewed every tick, released on shutdown) and creates `BackupJob`s for due schedules. Backup content travels collector → Redis (`dv:blob:job:<id>`, 24 h TTL) → storage worker; a job is `stored` only when the collector and storage worker report the same SHA-256.

### Worker runtime (pure Celery + kombu, **no Django**)

The worker has a bootstrap, registration, and control layer, plus driver registries: `collectors/` and `storage/`.

## 3. Repository layout

```
protocol/        shared package: queue/exchange names, message schemas (pydantic), envelope crypto;
                 from phase 11 also identity, registration agent, task trust and blob staging
orchestrator/    Django project + apps (pyproject, depends on protocol)
worker/          Celery worker runtime + drivers (pyproject, depends on protocol)
receiver/        push receiver: SCP/SFTP (asyncssh) and TFTP listeners, no Celery worker pool (phase 12)
frontend/        Quasar/Vue SPA (TypeScript)
docker/          Dockerfile (targets: orchestrator, worker, dev), web.Dockerfile, entrypoints, nginx template
deploy/
  infra/         compose: postgres, rabbitmq, redis (+ example HA notes)
  orchestrator/  compose: web, api, events, scheduler, flower(profile)
  worker/        compose: worker (env: DV_BROKER_URL, DV_REDIS_URL, DV_TLS_CA?, DV_WORKER_NAME?)
  receiver/      compose: receiver (same env as worker; network_mode: host)
  dev/           compose overlay: everything on one host, bind-mounted source, hot reload
docs/            ARCHITECTURE.md, DEPLOYMENT.md (later: OPERATIONS.md, DRIVERS.md, SECURITY.md)
CLAUDE.md
```

Tooling: a `uv` workspace (one lockfile), `ruff`, `pytest`; `npm` with a lockfile, `engines.node >= 24`, ESLint, Vitest. Everything is pinned. A top-level `Makefile` (`make lint`, `make test`, `make images`) is the single entry point and stays CI-agnostic, so a future GitLab or Gitea pipeline can just call it. No GitHub Actions.

**Removed:** `devicevault.sh`, `devicevault-docker-dev.sh`, `start-*.sh`, `setup/`, `scripts/`, `docker-build/`, `dev-env/`, `var/`, `original_prompt.txt`, `PRODUCTION_DEPLOYMENT_SUMMARY.md`, `backend/dv_*` empty apps, the one-off migrate/show scripts, the committed sample backup, the current `docs/*` (replaced by the set above), all existing migrations (squashed to a fresh `0001`), and MySQL support.

## 4. Identity, trust and crypto

### 4.1 Worker identity

- On first start the worker generates `worker_id` (UUIDv4), an **Ed25519 signing key** and an **X25519 encryption key**, and keeps them in `identity.json` in the state volume (`DV_STATE_DIR`, default `/var/lib/devicevault`, mode 0600). This is self-generated state, not configuration. Deleting it resets the worker: it registers again under a new id.
- The worker logs `worker_identity` with its SSH-style fingerprint (`SHA256:…`) so an admin can check it before approving.

### 4.2 Registration → approval → assignment (built in phase 4)

Message formats are in `protocol/src/devicevault_protocol/registration.py`.

1. The Celery worker starts consuming only its own auto-delete direct queue `dv.worker.<id>`. A registration agent thread in the main process listens on `dv.worker.<id>.control` and sends a signed (worker key) `register` event, then `heartbeat`s every 30s. Events are Celery tasks `orchestrator.worker_event` on `dv.orchestrator`, expiring after 120s, and carry the worker's capabilities (collector and storage drivers, with their parameter schemas), the applied assignment version and the orchestrator key it pinned.
2. The orchestrator's `events` process records the worker as `pending`. The first event fixes the worker's signing key, so later events with the same id but another key are rejected. Pending workers are sent nothing.
3. An admin approves the worker in the UI (or with `manage.py approve_worker`) after comparing fingerprints, choosing a **role** and either **collection groups** (collectors) or **storage targets** (storage; optional at approval, also assignable from the Storage Targets page).
4. The orchestrator sends a signed assignment `{version, status, role, queues, orchestrator_key}` to the control queue. Versions only increase, and the orchestrator never falls behind a version a worker reports (for example after a worker is forgotten and re-registers, or a database restore).
5. The worker verifies the assignment, ignores stale versions, and applies the queue difference with Celery's own `add_consumer`/`cancel_consumer`. The next heartbeat reports the new version, and the orchestrator re-sends while they differ. Nothing is cached: after a restart the worker idles until the assignment arrives again.
6. **Revoke** sends an assignment with no queues. **Forget** revokes and deletes the record; a worker that is still running comes back as pending.

**Trust on first use:** the worker pins the orchestrator key from the first *approved* assignment that verifies against it, so the trust decision coincides with the admin's approval. After that, assignments signed with any other key are rejected, and so is every task (`device.collect`, `storage.store`, `storage.read`) not signed by the pinned key. Tasks rejected this way fail immediately and are not retried. The Workers page shows the orchestrator's fingerprint and flags a worker that pinned a different one. Changing `DV_SIGNING_KEY` means resetting every worker's state.

**Limitations:**
- Broker credentials are shared per role, so revocation is enforced cryptographically (signatures and keys), not at the broker. Per-worker broker users can be added later.
- Celery remote control stays enabled because Flower needs it, so anyone holding broker credentials can still send Celery control commands (for example, to stop a worker consuming). They cannot forge assignments or tasks.

### 4.3 What is encrypted

| Data | Protection |
|---|---|
| All transports | TLS (`amqps://`, `rediss://`) required outside dev |
| Every orchestrator→worker message/task | Ed25519 signed |
| Device credentials and location config at rest | AES-256-GCM with the data key ring (`DV_DATA_KEYS`), bound to their table and column |
| Device credentials in a collect task | (when payload encryption is on) **Sealed per recipient**: one copy per approved collector of the device's collection group, each encrypted to that worker's X25519 key (ECIES: ephemeral X25519, HKDF-SHA256, AES-256-GCM). Any approved group member can open its copy, nobody else can. With 6-8 collectors this is cheaper and simpler than distributing group keys, and needs no re-keying when membership changes; a collector approved after a job was queued cannot open that job's credentials, and the job fails clearly. |
| Storage target settings (paths, bucket and S3/DB credentials) | Encrypted at rest like credentials. In transit (when payload encryption is on) sealed per recipient in each store/read/check task, to the target's own workers. Secret settings are write-only in the API. |
| Backup content | (when payload encryption is on) Encrypted **on the collector** to the orchestrator **vault public key**: per-backup DEK, AES-256-GCM chunked (existing `DVLT` format), DEK wrapped via X25519/HKDF. Storage workers, Redis, and RabbitMQ only ever see ciphertext. The orchestrator decrypts for view/diff. Vault keys form a key ring (kid) for rotation. |

**Payload encryption is a global orchestrator setting** (`DV_PAYLOAD_ENCRYPTION`, off by default for development, on for deployments). It covers backup content and secrets in transit. Every collect task carries the current vault public key (or none), signed like the rest of the task, so collectors need no state for it. When it is off, payloads go in plaintext (`enc_version=0`) so developers can inspect queues and Redis. Reads handle both versions. The per-device `encrypt_backups` toggle is removed. Message signing and credential encryption at rest are **always on** whatever this setting says. The orchestrator logs a startup warning when payload encryption is off with `DEBUG=false`.

Orchestrator secrets (Django secret, master key, vault private keys, signing key) come from env or Docker secrets. There is no `config.yaml`.

### 4.4 Authentication, authorization and audit (phases 8-10)

Status: phases 8-10 **implemented** (2026-10-24). Replaces the role-based device-group RBAC and the staff/superuser admin check.

Phase 10 notes: ID tokens are validated with `joserfc` (authlib 1.9 deprecated `authlib.jose` in its favour); authlib provides the PKCE challenge and token generation. Pending sign-ins (state, nonce, verifier, return path) live in the server-side session for 10 minutes, at most five per browser. Discovery and JWKS are cached for an hour and the JWKS refetched once on a signature failure (key rotation). Claims the ID token lacks come from userinfo when its `sub` matches. Phase 9 notes: `login_group` is the provider's group name (matched like mapping rules) rather than a user group, so it works before any group exists. Provider kinds live in `accounts/providers/` (a `ProviderKind` with a pydantic `Config`); their schemas drive the UI form as storage drivers' do. A provider's slug tags the memberships it adds and is fixed once created. A provider that is unreachable is skipped (and named in the failed sign-in's audit entry); a user the provider vouches for but its rules refuse gets a distinct 403. Phase 8 notes: contents, downloads and diffs are separate endpoints (`backups/<id>/content/`, `download/`, `compare/?a=&b=`), so each is checked and audited on its own. Credential data is write-only for everyone; a key sent as null keeps its stored value. Shared reference data that is not secret (types, manufacturers, schedules, retention policies) is readable in full; collection groups and storage targets are a summary for anyone but global admins. Sign-in failures are counted from the audit log, so throttling is shared by every node.

#### Concepts

- **User**: a local account (password in the DB) or an external one (LDAP, OIDC) created on first login. External users have no usable password.
- **User group**: a named set of users. *Internal* groups are managed by hand. *External* groups are created from a provider's group names and filled only by that provider's logins. A group optionally carries the **Global administrator** flag.
- **Device group**: unchanged, a set of devices.
- **Grant**: one row per (user group, device group) holding the permission flags below. A user's effective permissions on a device group are the union (OR, per flag) of the grants of all the groups they belong to. There are no deny rules.
- **Global administrator**: a member of any group with the flag. Holds every permission on every device group, including devices that are in no group, and is the only role with application administration: users, user groups and grants, auth providers, device groups, collectors and collection groups, storage targets and drivers, workers, Flower, schedules, retention policies, credential types, audit log. `is_staff` / `is_superuser` no longer authorize anything, and Django's `/admin/` site is removed.

#### Permission set

| Flag | Meaning | Requires |
|---|---|---|
| `view` (View Status) | See the device group, its devices, and job state, history, sizes and error summaries. Without it the group does not exist for the user. | none |
| `backup_now` | Start a backup now | `view` |
| `view_contents` | See and diff backup contents | `view` |
| `download` | Download backup contents | `view_contents` |
| `admin` (Group Administration) | Everything above, plus add, edit, enable/disable and delete devices in the group, use the shared reference data, and manage the group's own credentials | all of the above |

The dependency rules are enforced in the serializer, the model (`CheckConstraint`s) and the UI. Saving `admin` ticks the other four. A grant row without `view` is invalid; remove the row to revoke. Backup contents are never visible to a user who has only `view`: contents, diffs and downloads all require the flag on the device's group, and a diff needs it on both sides (always the same device, hence the same group).

Group administration also covers, for devices in its group:
- **Reference data**: pick existing schedules, retention policies, collection groups, storage targets, backup methods and credentials when onboarding. Group admins get a minimal read serializer (id, name; never storage settings or secrets). Creating or changing that data is global-admin only.
- **Credentials**: `Credential` gains a nullable `device_group` owner. Global credentials (no owner) are created by global admins and usable by every group admin. Owned credentials are created, edited, deleted and used only by admins of that group. Secrets stay write-only everywhere. A device may only reference a global credential or one owned by its own group, checked on every device write.
- **Moving a device** to another group needs `admin` on both groups. Creating, renaming and deleting device groups is global-admin only. `Device.device_group` stays nullable: ungrouped devices are visible and manageable by global administrators only.

Action to permission, enforced in the API (the UI only hides things):

| Action | Needs |
|---|---|
| List/retrieve devices, groups, jobs, dashboard counts and recent activity | `view` on the device's group (querysets are filtered, a hidden object is a 404) |
| `POST /devices/<id>/backup-now/` | `backup_now` |
| Backup content, compare | `view_contents` |
| Backup download | `download` |
| Create, update, delete, enable/disable a device | `admin` on its group (global admin for ungrouped) |
| Credentials | list: global ones and owned by groups the user administers; write: `admin` on the owner group, or global admin |
| Everything else under application administration | global administrator |

#### Data model (new app `accounts`; `core.UserProfile` gains `break_glass`)

- `UserGroup`: name (unique), description, `is_global_admin`, `source` (`internal`/`external`), `provider` (FK, external groups only), `external_id`. The built-in internal group **Administrators** (global admin) is created by the bootstrap admin step and can be neither deleted nor stripped of its flag.
- `UserGroupMembership`: user, group, `source` (`manual` or the provider that supplied it). Provider syncs only touch rows with their own source, so manual membership is never lost.
- `DeviceGroupGrant`: user_group, device_group, five boolean flags, unique per pair, check constraints for the dependency rules.
- `AuthProvider`: slug, name, `kind` (`ldap`/`oidc`), enabled, `order`, `config` (`EncryptedJSONField`, validated against the kind's pydantic model, secrets write-only like storage settings), `auto_create_users` (default on), `login_group` (optional: external group the user must be in to log in), `auto_create_groups`.
- `GroupMappingRule`: provider, `external_group` (exact match, case-insensitive for LDAP), `user_group` (internal or external).
- `ExternalIdentity`: provider, `subject` (immutable id), user, unique per (provider, subject).
- Dropped: `DeviceGroupRole`, `DeviceGroupPermission`, `UserDeviceGroupRole`, `GroupDeviceGroupRole`, `DeviceGroupDjangoPermissions` and the per-group `dg_*` Django permissions with their signals, `django.contrib.auth.Group` usage, `rest_framework.authtoken`.
- Single enforcement module `accounts/access.py`: `is_global_admin(user)`, `grants_for(user)` (a `{device_group_id: frozenset[flag]}` map, computed once per request), `can(user, flag, device_group)`, `visible_device_groups(user)` and a `Device` queryset helper. DRF classes `IsGlobalAdmin`, `IsGlobalAdminOrReadOnly` (reads for authenticated users, as `IsAdminOrReadOnly` today) and `HasDeviceGroupPermission(flag)`. These replace `api/permissions.py` and `devices/permissions.py`; there is no second checker.

#### Sessions

Server-side Django sessions replace DRF tokens for every login method. The cookie is HttpOnly, `SameSite=Lax` (needed for the OIDC redirect), `Secure` outside dev; sessions live in the database so both orchestrator nodes share them, and the scheduler leader prunes expired ones. CSRF is enforced for unsafe methods: `GET /api/auth/csrf/` sets the cookie, the SPA sends `X-CSRFToken`. Timeouts are an idle timeout and an absolute lifetime. The Flower cookie (decision 12) binds to the session instead of the token. Permissions are read from the database on every request, so a grant, membership or `is_active` change applies immediately for internal changes; for external groups it applies at the user's next login, bounded by the absolute lifetime.

#### Login flows

- **Local**: `POST /api/auth/login/` with username and password. When `DV_LOCAL_AUTH_ENABLED=false` only **break-glass** users (a flag on local users, set on the bootstrap admin, toggled by global admins) can still use it.
- **LDAP / AD**: the same form. The orchestrator tries local users first, then each enabled LDAP provider in `order`. Implemented with `python-ldap` directly, because `django-auth-ldap` reads one static Django-settings configuration and providers here are database records. Search-and-bind: bind as the service account, search the user with a filter (the username is escaped), bind as the found DN with the password. Config: server URIs (several, for failover), LDAPS or StartTLS, CA bundle, bind DN and password, user base and filter, attribute map (username, email, first and last name), identity attribute (`entryUUID`, or `objectGUID` for AD), group base and filter or a `memberOf` attribute, optional nested-group matching (AD `LDAP_MATCHING_RULE_IN_CHAIN`), timeouts. The orchestrator must reach the directory.
- **OIDC** (Entra ID, Okta, Authentik, any compliant IdP) using `authlib`: Authorization Code with PKCE, discovery URL, client id and secret, scopes, username claim, groups claim (default `groups`), ID-token validation against the IdP's JWKS, state and nonce. The login page lists enabled OIDC providers as buttons. `GET /api/auth/oidc/<slug>/login/` redirects out and `GET /api/auth/oidc/<slug>/callback/` creates the session and redirects into the SPA; the redirect URI to register at the IdP is shown in the provider form. Logout is local, with optional IdP end-session redirect.
- **Linking**: an external login matches only on (provider, immutable subject: OIDC `sub`, LDAP identity attribute). It never matches on username or email, so an IdP-controlled email cannot take over a local or other account. A new username that collides is made unique. Name and email are refreshed at each login.
- **Provisioning**: first login creates the user when `auto_create_users` is on, and the user lands with no access until a group grants some. `login_group`, if set, refuses everyone not in it.
- **Group sync** at each login: the provider's group names are matched to `GroupMappingRule`s; with `auto_create_groups`, unmatched names also become external user groups (named `<provider>:<name>`, no grants). The user's provider-sourced memberships are set to exactly that result, adding and removing.
- **Limitation**: Entra ID omits the groups claim and sends an overage pointer above ~200 groups. This phase does not follow it. Configure the app to emit assigned groups/roles only, and log a warning when the pointer is seen.

#### Safeguards

- Login throttling per username and per IP (`DV_LOGIN_MAX_FAILURES` within `DV_LOGIN_LOCKOUT_MIN`), applied to local and LDAP; the same generic error is returned for unknown user and wrong password.
- The last active global administrator cannot be disabled, deleted, removed from the flagged group, or have the flag removed; nor can users disable or delete themselves.
- Local passwords use Django's validators; external users cannot set passwords.
- Provider secrets (OIDC client secret, LDAP bind password) are encrypted at rest and never returned by the API. A provider's **Test** action checks discovery/JWKS (OIDC) or bind plus a sample user and group lookup (LDAP).

#### Audit

The existing `AuditLog` is extended with `outcome` (`success`/`failure`/`denied`), `actor_name` (a snapshot, so failed logins by unknown names and deleted users stay readable), `ip`, `user_agent`, and a nullable `device_group` (replacing `label_scope`). Recorded: logins and failures (provider, reason), logout and session expiry; user, user-group, grant, membership, provider and mapping-rule changes and global-admin flag changes, each with before and after; backup content views, diffs and downloads (device, job, group); authorization denials (403) and Backup Now (who, device). Global administrators can read and filter the log; group-scoped log access is later.

#### Configuration

Identity providers are data, edited in the UI. Only security knobs and bootstrap stay in the environment (documented in `docs/DEPLOYMENT.md` and `orchestrator.env.example` with each phase):

| Variable | Default | Meaning |
|---|---|---|
| `DV_LOCAL_AUTH_ENABLED` | `true` | Allow local users to sign in (break-glass users always can) |
| `DV_SESSION_IDLE_MIN` | `60` | Idle session timeout |
| `DV_SESSION_MAX_HOURS` | `12` | Absolute session lifetime |
| `DV_LOGIN_MAX_FAILURES` / `DV_LOGIN_LOCKOUT_MIN` | `5` / `15` | Throttle |
| `DV_ADMIN_*` | as today | Bootstrap: creates a local, break-glass member of Administrators |

#### Frontend

- **Users**: list with source (local or provider), active state, groups; create local users, disable, reset a local password, break-glass toggle.
- **User Groups**: editor per group: members, global-admin tick, and the group's grants as a list of device groups with the five flags (dependent boxes tick and disable themselves). External groups show membership read-only.
- **Access** (read-only matrix): device groups as rows, user groups as columns, each cell the flags held (`S B C D A`), filterable on either axis, global-admin groups highlighted.
- **Auth Providers**: LDAP and OIDC forms (schema-driven like storage targets), mapping rules, Test.
- **Audit log** page for global administrators.
- `GET /api/auth/user/` returns `is_global_admin` and `grants`; the auth store, router guard and the device, backup and credential pages use them to hide controls. This is cosmetic, as the API enforces.

#### Out of scope

MFA for local users; API keys and service accounts; per-device grants and deny rules; SCIM or scheduled directory sync (groups sync at login only); SAML 2.0 (may return as a provider kind, since providers are pluggable); delegated membership management by group admins (group admins see no user administration); Entra group-overage resolution.

#### Delivery

1. **Phase 8 `feat/aaa-rbac`**: `accounts` app, groups, memberships and grants, `access.py` replacing both checkers, enforcement across every view (`CLAUDE.md` rule: every view states its permission class), credential ownership, sessions replacing tokens, audit extension, Users / User Groups / Access / Audit pages, drop of the old RBAC, local auth only.
2. **Phase 9 `feat/auth-providers`**: provider records, mapping rules, group sync, linking, break-glass, LDAP, Auth Providers UI.
3. **Phase 10 `feat/auth-oidc`**: OIDC provider kind and login flow; tested against a mock IdP.

Tests, per phase: the dependency rules (model, API), the union semantics, a matrix of role x endpoint (including that hidden objects 404 and contents/download are refused), the last-admin guard, CSRF, session timeouts, identity linking (no email takeover), group sync add and remove, LDAP filter escaping, and OIDC state/nonce/signature failures.

## 5. Backup data path

Large payloads don't go through RabbitMQ: RabbitMQ 4 defaults to a 16 MiB message cap, and backups can be tens of MB. Instead, **blobs are staged in Redis** (ciphertext when payload encryption is on) (`dv:blob:<uuid>`, TTL 24h). Messages carry only `{blob_ref, sha256, size}`. Redis streams are dropped: all events go over RabbitMQ (durable quorum queue `dv.orchestrator`), so retries and acks are uniform.

```
scheduler/api ── BackupJob(queued) ──► collect task → collector.group.<g>
collector:  lock dv:lock:device:<id> → driver.collect() → encrypt (if enabled) → stage blob
            → store task → storage.target.<t>   (target queue was in the job)
            → job.collected event → dv.orchestrator
storage:    fetch blob, verify sha256 → driver.store() → delete blob
            → job.stored {storage_ref, size, enc meta} → dv.orchestrator
events:     BackupJob state machine: queued→collecting→collected→stored | failed | timed_out
read (UI):  api → storage.read task → storage.target.<t> → blob dv:blob:read:<uuid> (10 min TTL)
            → Celery result {key, sha256, size} → api checks the hash, decrypts
check (UI): api → storage.check task → storage.target.<t> → Celery result
```

Push (section 7.1) joins this path at the store step:

```
receiver:   accept upload (auth, source IP, filename) → spool to disk → encrypt (if enabled) → stage blob
            → push.received event → dv.orchestrator
events:     re-check device → BackupJob(trigger=push, collected) → signed store task → storage.target.<t>
storage:    as above → job.stored
```

**Large blobs (phase 11):** Redis caps one value at 512 MB (`proto-max-bulk-len`), and a 512 MiB push plus encryption overhead exceeds it. Blob staging moves to chunks (`dv:blob:<uuid>:<n>`, 32 MiB each, plus a manifest key holding the chunk count, size and SHA-256), written and read in a stream so neither side holds a whole backup in memory. Small backups are one chunk. Redis `maxmemory` must allow for the largest expected backups in flight (DEPLOYMENT.md).

Retries: drivers raise typed errors. Transient errors (timeout, connection refused, lock held) trigger a Celery retry with backoff. Permanent errors (auth failure, unknown driver) fail the job. Each job is handled exactly once, keyed on `job_id`. Binary/text is carried as job metadata end to end, which fixes the dropped `is_binary` flag.

## 6. Data model (main changes)

- `Worker` (replaces `WorkerRegistration`): id, name, status (pending/approved/revoked), role, public keys, capabilities, assignment version applied/desired, last_seen.
- `CollectionGroup`: queue `collector.group.<uuid>`, M2M workers. The UI warns when a device's driver isn't supported by every approved member.
- `StorageTarget` (replaces `BackupLocation`): name, driver key, config (validated against the driver schema, secret fields encrypted), M2M workers, queue `storage.target.<uuid>`. Assigning a non-`shareable` driver (local fs, local git) to more than one worker is blocked.
- `Device`: `driver` + `driver_params` (validated against the driver schema), collection_group, storage_target, credential, schedule (FK; currently missing, which is why schedules never fire), retention_policy. From phase 12: `ip_address` unique across all devices, and `push_mode` (off / ssh / tftp) with an optional `push_filename_pattern` (glob).
- `Worker` (phase 12): role `receiver`, and `runtime`, what a receiver reports in its heartbeats (listeners, host key fingerprint, vault key in use). New app `push`: `ReceiverSettings` (one per receiver: protocol switches, ports, listen address, max file size, encrypted shared login) and `PushRejection` (the latest refusals per receiver). `BackupJob` gains trigger `push` and `source_filename`. See section 7.1.
- `BackupJob` (replaces `DeviceBackupResult` + `StoredBackup`): one row per attempt with state, timings, logs, storage_ref, enc metadata, size, sha256.
- `FlowerEndpoint`: name, slug, url, proxied (bool). Admin-only. Proxied endpoints are served at `/flower/<slug>/`.

## 7. Driver framework

**Collector driver** (`worker/collectors/`):
```python
class CollectorDriver(Protocol):
    key: str
    version: str
    mode: Literal['pull']  # "push" reserved
    Params: type[BaseModel]  # → JSON Schema → UI form

    def collect(self, target: Target, creds: Creds, params: Params, timeout: int) -> Collected: ...
```
Bases: `NetmikoDriver` and `ScrapliDriver` (a vendor driver is then mostly a command list plus a cleanup regex). The first drivers are ported from today's: Mikrotik, plus `noop` and `binary_dummy` for tests. Cisco IOS/ASA etc. come later from your specs.

Push collection is not a collector driver mode; it is a separate receiver component (section 7.1).

**Storage driver** (`worker/storage/drivers/`): `store(data, name, params) → ref`, `read(ref, params) → bytes`, `delete(ref, params)`, `check(params)`, plus `Params`, `shareable`. Drivers (phase 6): filesystem and git (paths relative to the worker's `/srv/devicevault` volume, not shareable) and S3 (shareable); PostgreSQL (shareable, psycopg 3, one `bytea` row per backup in `<schema>.devicevault_backups`, with discrete connection and TLS settings). Other databases get drivers of their own rather than a generic SQLAlchemy URL, since TLS and connection settings differ for each.

Drivers are discovered through Python entry points, so a new driver can ship as a separate package without editing core.

### 7.1 Push collection (phases 11-13)

Devices upload their configuration unprompted (for example Cisco `archive` on `write memory`) over SCP, SFTP or TFTP. Pushing sits alongside polling: a device keeps its driver and schedule and may also push.

**Receiver component.** A separate image built from the `receiver/` package (`devicevault_receiver`), so collectors stay unexposed to inbound traffic and the listening process carries no collector dependencies. It is not a Celery worker: it registers like any worker (identity, signed events, approval with fingerprint check, TOFU pinning; the code shared with `worker/` moves into `protocol/` in phase 11), consumes only its control queue, and sends events. It is approved with role `receiver` on the Workers page.

**Networking.** The receiver runs with `network_mode: host` (`deploy/receiver`). Bridge networking would break both requirements: Docker's userland proxy (IPv6, hairpin traffic) replaces the device's source address, which is how devices are matched, and TFTP answers from a new ephemeral port that DNAT doesn't follow without the conntrack helper. With host networking a listener's socket is bound only while its assignment enables it and is closed when disabled, so a port is open only when configured. Default ports are unprivileged (2222 for SCP/SFTP, 6969 for TFTP); ports 22 or 69 need `CAP_NET_BIND_SERVICE` or a host firewall redirect (DEPLOYMENT.md).

**Settings (per receiver, Workers page).** SCP/SFTP on/off and port, TFTP on/off and port, maximum file size (default 512 MiB), and a shared SSH login: username, password and optional authorised public keys, encrypted at rest and sealed to that receiver. The receiver generates its SSH host key on first start and keeps it in its state volume next to `identity.json`; it reports the fingerprint in its events and the UI shows it so it can be pinned on devices.

**Assignment.** Settings travel in the receiver's signed assignment rather than per task (there is no task), together with the vault public key and the payload-encryption switch, and the list of push-enabled devices: `{id, ip, push_mode, filename_pattern}`. Every receiver accepts every push-enabled device. A change to any push-enabled device, or to the receiver's settings, bumps receiver assignment versions. Sealed secrets in an assignment are re-sealed per receiver like task secrets. A receiver reports the vault key id it uses in its heartbeats, and one that is in sync but behind the current key (after a rotation) gets a new assignment.

**Device settings.** `push_mode`: off, `ssh` (SCP or SFTP) or `tftp`. TFTP is an explicit per-device opt-in, flagged in the UI as unauthenticated (UDP source addresses can be forged); an `ssh` device's pushes over TFTP are rejected. An optional `push_filename_pattern` (glob) restricts accepted filenames. `Device.ip_address` becomes unique across all devices so a source address names exactly one device; source addresses are normalised (IPv4-mapped IPv6 → IPv4) before matching. A push-enabled device must have a storage target.

**Accepting a file.** The receiver checks, in order: the SSH login (SCP/SFTP), that the source address is a push-enabled device whose `push_mode` matches the protocol, the filename pattern, and the size limit (checked while streaming; SFTP/SCP transfers and TFTP sessions also have an idle timeout). The upload is spooled to a temporary file in the state volume, then encrypted to the vault key (when enabled) and staged as a chunked blob (section 5). Each accepted file is its own backup. The receiver picks the job id, since the encryption binds the backup to it (AAD `job_id`, `device_id`), and sends a signed `push.received` event `{job_id, device_id, source_ip, protocol, filename, blob, is_binary, encrypted}` (Celery task `orchestrator.push_event`; formats in `devicevault_protocol.push`). The client's close of the file fails if staging fails, so the device sees the upload fail.

**Orchestrator side.** The `events` process verifies the signature and that the sender is an approved receiver, checks that the blob key is the job's own, re-checks the device (exists, enabled, push enabled with that protocol, IP and filename pattern still match, has a storage target; otherwise the blob is deleted and a `device_changed` refusal recorded), creates a `BackupJob(trigger=push)` with the receiver's job id, already `collected`, with the filename as metadata, and sends the signed store task to the device's storage target. From there it is the normal pipeline. Push jobs are exempt from the "one active job per device" rule, so two quick pushes, or a push during a scheduled poll, don't drop a file.

**Rejections.** Unknown sources, failed logins, wrong protocol, filename or size are refused at the protocol level (SSH authentication failure or SFTP/SCP error; TFTP access-violation error), and nothing is stored. The receiver sends a rate-limited signed `push.rejected` event `{source_ip, protocol, reason, filename?}`; the orchestrator audits it and the receiver's page lists recent rejected sources, which helps when onboarding a device with the wrong address.

**Libraries.** `asyncssh` serves SCP and SFTP from one SSH server (upload only: no shell, exec, port forwarding, reads or listings beyond what clients need to write). TFTP is a small asyncio server for write requests only (RFC 1350 with blksize/tsize options, RFC 2347-2349), as `tftpy` is unmaintained and synchronous.

## 8. HA

- Two orchestrator nodes. `web`/`api`/`events` are active/active. `scheduler` runs on both but only the Redis-lease leader acts. The standby takes over at its next tick when the leader stops cleanly (the lease is released), or once the lease expires (60 s by default) when it dies. The leader re-checks the lease before each due schedule, so one that stalled past its lease stops scheduling.
- The front-end VIP/load balancer (keepalived, or an existing LB) sits outside the stacks. A keepalived example is documented in DEPLOYMENT.md.
- HA needs PostgreSQL. **SQLite = single orchestrator node only**, enforced at startup: each database has an installation id, and `migrate` claims Redis for it (`dv:orchestrator:installation`), so a node whose database differs (such as a second SQLite file) refuses to start. SQLite runs in WAL mode with immediate transactions, which is fine at this scale.
- Infra HA (Postgres replication, a 3-node RabbitMQ cluster, Redis Sentinel) is out of the compose stacks. PostgreSQL (`DV_DB_HOST=pg1,pg2`, connecting to the writable one) and RabbitMQ (`;`-separated broker URLs) accept several hosts; Redis is a single endpoint until Sentinel support is added.
- Flower: each node's `web` proxies `/flower/<slug>/` to Flower after asking the API (`auth_request` to `/api/flower-auth/`), which checks the browser's session cookie and names the upstream. A Flower on every node at `http://flower:5555` keeps it available through either node.

## 9. Frontend

Rewritten with TypeScript, `<script setup>`, Pinia, a typed API client, and Vitest. Device and storage-target forms are rendered from driver JSON Schemas. New admin pages: Workers (pending approvals, fingerprint, role/assignment, liveness), Storage Targets, Flower.

## 10. Phases (one branch and PR each)

| # | Branch | Content | Master stays working? |
|---|---|---|---|
| 0 | `plan/architecture` | This document and `CLAUDE.md` | yes |
| 1 | `chore/foundation` | New layout, uv workspace, Py 3.14, Django 6.1, pinned deps, ruff/pytest, `Makefile`, cruft and docs removal, squashed migrations, MySQL removed, unused external-auth deps removed | yes (behaviour unchanged) |
| 2 | `feat/deploy-layout` | Dockerfiles, `deploy/{infra,orchestrator,worker,dev}`, `protocol/` + `worker/` packages (worker de-Djangoed, still old routing), env-only config | yes |
| 3 | `feat/frontend-rewrite` | Port of existing pages to TypeScript, `<script setup>`, Pinia and Vitest, with shared CRUD/dialog components; fixes for device writes and API access control found on the way | yes |
| 4 | `feat/registration` | Worker identity and keys, signed events/assignments/tasks with TOFU pinning, register/approve/assign/revoke, `events` process, Workers UI; workers need no queue config and the orchestrator no longer depends on the worker package | yes |
| 5 | `feat/pipeline` | BackupJob, scheduler (fixes schedules), blob data path, collector-side encryption, per-recipient sealed secrets, credential encryption at rest, retry semantics, collector driver framework (Netmiko base; Cisco IOS and MikroTik drivers), schema-driven device form | yes |
| 6 | `feat/storage-targets` | StorageTarget per worker, storage driver framework (fs, git, s3), reads, UI | yes |
| 7 | `feat/flower-ha` | FlowerEndpoint and nginx proxy, scheduler leader election verified with 2 nodes, HA docs | yes |
| 8 | `feat/aaa-rbac` | User groups, device-group grants and the permission matrix, global administrators, server-side sessions, audit extension, replaces the old RBAC (section 4.4) | yes |
| 9 | `feat/auth-providers` | Auth provider records, group mapping and sync, identity linking, break-glass, LDAP | yes |
| 10 | `feat/auth-oidc` | OIDC provider kind (Entra, Okta, Authentik) | yes |
| 11 | `refactor/shared-agent` | Identity, registration agent, task trust and blob staging move from `worker/` into `protocol/`; chunked, streamed blob staging (section 5). No behaviour change otherwise | yes |
| 12 | `feat/push-receiver` | `receiver/` package, `receiver` image target and `deploy/receiver`; receiver role and settings; SCP/SFTP listener; `push.received`/`push.rejected` events → BackupJob; device push settings and unique IP; UI (section 7.1) | yes |
| 13 | `feat/push-tftp` | TFTP write-only listener and the per-device TFTP opt-in | yes |
| later | — | Retention enforcement, new vendor drivers, Redis Sentinel | — |

Each backend phase ships its own UI changes, so master never has a broken frontend.

## 11. Decisions log

| # | Decision |
|---|---|
| 1 | Orchestrator signing key is TOFU-pinned by workers at first assignment; recovery is a worker state reset. |
| 2 | Payload encryption is a **global orchestrator option**: off for development, on per deployment (see 4.3). |
| 3 | Redis streams dropped. Events go over RabbitMQ, and payloads are staged in Redis as blobs. |
| 4 | Infra HA and the front-end VIP/LB are documented, not shipped in compose. |
| 5 | Config comes from env and Docker secrets only; no `config.yaml`. SQLite→Postgres migration is a `manage.py` command. |
| 6 | External auth (LDAP/SAML/Entra) deps removed; external auth becomes a later phase. Superseded by decisions 14-22 (phases 8-10); SAML is not planned. |
| 7 | No CI for now (no GitHub Actions minutes). A CI-agnostic `Makefile` is ready for a future GitLab or Gitea pipeline. |
| 8 | (phase 5) Secrets in transit are sealed per recipient worker rather than to collection-group keys: simpler, no key distribution or re-keying on membership change, and cheap at the expected 6-8 collectors. The vault public key and the payload-encryption switch travel in each signed task rather than in assignments. |
| 9 | (phase 5) Collector drivers use Netmiko for SSH CLI platforms; Scrapli can be added as a second base when a platform needs it. |
| 10 | (phase 6) Storage target settings travel in each signed storage task (sealed to the target's workers) rather than in assignments, for the same reason as decision 8: workers keep no configuration state. Assignments carry only queues. Jobs protect their storage target from deletion, and a target's driver is fixed once it holds backups. |
| 11 | (phase 6) Reads and target checks are request/response tasks answered through the Celery result backend, not `read.result` events: the API needs the answer within the same HTTP request, which an event handled by any `events` process cannot give it. The content itself still travels through Redis, checked against the job's recorded SHA-256. |
| 12 | (phase 7) A proxied Flower is authorised by a short-lived signed cookie, scoped to `/flower/<slug>/` and bound to the user's API token, that the UI requests before opening it: the SPA's token lives in browser storage, which a new tab doesn't send. The API names the upstream in the `auth_request` response, so the nginx configuration stays static. |
| 13 | (phase 7) One database per message bus: `migrate` claims Redis for its database's installation id and a node with another database refuses to start. This enforces single-node SQLite and also catches nodes pointed at different PostgreSQL databases. |
| 14 | (phase 8) The role-based device-group RBAC (roles, per-group Django permissions, user and auth-group role assignments) is dropped for **user groups with grants**: one row per (user group, device group) holding five dependent flags (view, backup now, view contents, download, admin). Effective rights are the union across a user's groups; there are no deny rules. One checker (`accounts/access.py`). |
| 15 | (phase 8) **Global administrator** is a flag on a user group, not on the user. `is_staff`/`is_superuser` authorize nothing and the Django admin site is removed. The built-in Administrators group and the last active global admin are protected. |
| 16 | (phase 8) Server-side session cookies (HttpOnly, SameSite=Lax, CSRF) replace DRF tokens for all login methods, which makes OIDC redirects and server-side logout and timeouts straightforward. The Flower cookie binds to the session. |
| 17 | (phase 8) `Credential.device_group` is an optional owner: global credentials are admin-managed and shared, owned ones are managed and usable by that group's admins only. |
| 18 | (phase 9) Identity providers are database records edited in the UI, several can coexist, secrets encrypted at rest. This is application data, not deployment configuration, so it is an exception to decision 5; bootstrap and security timeouts stay in the environment. |
| 19 | (phase 9) External identities link on (provider, immutable subject), never on email or username. Provisioning is just-in-time per provider. |
| 20 | (phase 9) External group membership is synced at login only, by mapping rules and optional auto-created external groups, tagged by source so manual membership is untouched. |
| 21 | (phase 9) Break-glass: the bootstrap admin is a local user flagged to log in even when local authentication is disabled. |
| 22 | (phases 9-10) LDAP uses `python-ldap` directly (django-auth-ldap is single-configuration, settings-based); OIDC uses `authlib`. SAML is out of scope. |
| 23 | (phases 11-13) Push collection is a separate **receiver** component with its own image and role, not a collector capability: only the receiver is exposed to inbound traffic, and it carries no collector dependencies. Shared worker code moves to `protocol/` rather than the receiver depending on the worker package. |
| 24 | (phase 12) Receivers use **host networking**: bridge networking loses the source address (userland proxy, IPv6) and breaks TFTP's ephemeral reply ports, and only a socket bound at runtime keeps a port closed until it is configured. |
| 25 | (phase 12) Devices are matched on **source address only**, so `Device.ip_address` is unique across all devices. Every receiver accepts every push-enabled device. SCP/SFTP use one shared login per receiver as well as the address check; TFTP is unauthenticated and an explicit per-device opt-in. |
| 26 | (phase 12) Receiver settings, the push-enabled device list, the vault key and the encryption switch travel in the receiver's **assignment**, an exception to decision 10's queues-only assignments, since a receiver receives no tasks to carry them. |
| 27 | (phase 12) Pushing is a per-device setting alongside polling, not a backup method. Each accepted file is its own `BackupJob(trigger=push)`, exempt from the one-active-job rule. Rejected pushes are refused at the protocol level and reported (audited, shown per receiver), never quarantined. |
| 28 | (phase 11) Pushed files may be up to 512 MiB, beyond Redis's 512 MB value cap with encryption overhead, so blobs are staged in 32 MiB chunks and streamed. |
| — | Retention enforcement: in scope, designed in a later phase. |
