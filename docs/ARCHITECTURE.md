# DeviceVault — Target Architecture & Delivery Plan

Status: **Agreed** (2026-10-23). Decisions on the former open questions are recorded in section 11. Phases 8-10 (authentication, authorization and audit, section 4.4) were added on 2026-10-24; phases 8-10 are implemented. Push collection (unsolicited SCP, SFTP and TFTP uploads, section 7.1, phases 11-13) was added on 2026-10-24; phases 11-13 are implemented. Config search (ROADMAP Q6, section 7.2, phases 16-17) was added on 2026-10-25; phases 16-17 are implemented.

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
| `scheduler` | runs everywhere, **one leader** (Redis lock with TTL and renewal) | Reads `BackupSchedule` from the DB and dispatches due jobs. Sends liveness pings, times out stale jobs, and applies retention policies. Replaces celery beat, whose local schedule file isn't HA-safe. |

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

Tooling: a `uv` workspace (one lockfile), `ruff`, `pytest`; `npm` with a lockfile, `engines.node >= 24`, ESLint, Vitest. Everything is pinned. A top-level `Makefile` (`make lint`, `make test`, `make images`) is the single entry point and stays CI-agnostic: the GitHub Actions workflows (decision 29) only call its targets, so a GitLab or Gitea pipeline could do the same.

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
retention:  scheduler leader → expired BackupJobs → storage.delete task (batched) → storage.target.<t>
            → deleted | delete_failed event per backup → dv.orchestrator (job kept, marked pruned)
            (an inactive device past its hold: every unpinned backup; a purged one: every backup, section 7.5)
summary:    job stored → orchestrator.change_summary (signed, dv.orchestrator) → read it and the previous backup
            → decrypt, drop volatile lines, diff → changed, lines_added, lines_removed, lines_modified on the job
search:     same task, same bytes (when DV_CONFIG_SEARCH is on) → replace secrets with tokens
            → the device's SearchDocument (section 7.2)
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
A driver may declare `volatile_lines` (regexes for lines that change on every read); it advertises them, and the orchestrator ignores those lines when it summarises changes, including in files the device pushed (phase 15). `NetmikoDriver` also drops them at collection. A driver may also declare `secret_lines` (regexes whose groups are secret values, each with an optional known encoding), which config search replaces with tokens before indexing (phase 16, section 7.2).

Bases: `NetmikoDriver` and `ScrapliDriver` (a vendor driver is then mostly a command list plus a cleanup regex). The first drivers are ported from today's: Mikrotik, plus `noop` and `binary_dummy` for tests. Cisco IOS/ASA etc. come later from your specs.

Push collection is not a collector driver mode; it is a separate receiver component (section 7.1).

**Storage driver** (`worker/storage/drivers/`): `store(data, name, params) → ref`, `read(ref, params) → bytes`, `delete(ref, params)`, `check(params)`, plus `Params`, `shareable`. Drivers (phase 6): filesystem and git (paths relative to the worker's `/srv/devicevault` volume, not shareable) and S3 (shareable); PostgreSQL (shareable, psycopg 3, one `bytea` row per backup in `<schema>.devicevault_backups`, with discrete connection and TLS settings). Other databases get drivers of their own rather than a generic SQLAlchemy URL, since TLS and connection settings differ for each.

A storage driver also declares `deletes`: whether `delete` removes a backup. Retention only prunes targets whose driver does; git does not (phase 14).

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

### 7.2 Config search (phases 16-17)

"Which devices still have SNMP community `public`?" answered in seconds, over the **latest** backup of every device whose contents the user may see. Reading backups back through storage and decrypting them at query time would take minutes on a real estate, so the orchestrator keeps a search index, built when a backup is stored.

**Opt-in.** `DV_CONFIG_SEARCH` (default `false`). The index holds decrypted configuration in the orchestrator database, which nothing else there does: credentials and storage settings are encrypted with the data keys, backup content with the vault key. Secret values inside configs are not held in plaintext (see *Secret tokens*), but everything else in a config is. DEPLOYMENT.md says so.

**Engine: the orchestrator database.** On PostgreSQL, a `pg_trgm` GIN index on the document text speeds up both substring (`ILIKE`) and regex (`~*`) candidate queries. Engineers search for literals such as `10.12.4.`, `Gi1/0/2` or `ip helper-address`, which word-based full-text search handles badly (stemming, IP addresses and interface names split into tokens). On SQLite (single node, small estates) there is no index and candidates are scanned. Both sit behind `search/backend.py`, so an external engine could be added if an estate ever outgrows PostgreSQL. A separate engine (Solr, OpenSearch) is not used: an indexed-but-not-stored field still keeps every term and its positions in plaintext, so it protects nothing a database row doesn't, and it would add a service to run and a second copy of the permission model.

**Model** (new app `search`). `SearchDocument`, one per device (one-to-one, deleted with the device):
- `job`: the backup it was built from.
- `text`: the backup decoded as UTF-8 (invalid bytes replaced), `\r\n` normalised to `\n`, secret values replaced by tokens. Volatile lines are kept, so line numbers match the backup viewer.
- `token_kid`: the data key id the tokens were made with.
- `patterns_hash`: a fingerprint of the secret patterns (and encodings) applied.
- `indexed_at`.

Only the latest backup is indexed. Searching history is a possible later extension; it would key documents by content so that unchanged backups share one.

**Indexing.** The post-store task (`orchestrator.change_summary`, run by `events`, decision 32) already reads and decrypts the new backup. When search is on, it also builds the device's document from the same bytes, so a backup is read once. The task replaces the document only if its job is newer than the document's (tasks can run out of order). When the summary skips the read (two unencrypted backups with equal hashes), the document just moves to the new job. Binary backups and backups over 16 MiB are not indexed: the device's document then has no text and says why (`skipped`), rather than describing an older config, so searches leave it out and the catch-up pass leaves it alone. A read that fails is retried like the summary's.

**Catch-up pass.** Every five minutes the scheduler leader queues signed index-only tasks (`orchestrator.search_index`, at most 200 per pass, each device at most once an hour, marked in Redis) for devices whose newest stored backup:
- has no document (search just turned on, or a failed read), or
- has a document built with another `token_kid` (data key rotated), or
- has a document whose `patterns_hash` differs from the current driver catalogue (driver upgraded).

This makes enabling search, rotating keys and upgrading drivers self-healing, without a command. `manage.py reindex_search` forces every device. With search turned off, the pass deletes every document and the search endpoints answer 404.

**Secret tokens.**
- Drivers declare `secret_lines` next to `volatile_lines`: regexes matched per line (after `lstrip`, like volatile lines), whose capture groups are secret values. Each pattern can name an `encoding` for reversible encodings. Collectors advertise them; the orchestrator bounds and validates them like volatile lines: they must compile and have at least one group.
- Encodings are a fixed orchestrator-side list (first `cisco7`), since the orchestrator never runs worker code. A value with a known encoding is decoded before hashing, so typing `cisco` finds `password 7 0822455D0A16`.
- Each value is replaced by `{{secret:<32 hex>}}`: HMAC-SHA256 of the value, truncated to 128 bits. The HMAC key is derived from the current data key (HKDF-SHA256, info `devicevault/search-token`). It is never stored in the database or sent to the browser, so a database dump alone cannot be brute-forced against a dictionary of likely secrets.
- Equal secrets give equal tokens, so a dump shows which devices share a secret without revealing it. This is accepted; it is also what makes secret search work.
- Salted hashes (Cisco type 5/8/9, `$6$`...) are tokenised as their literal string; they are only found by pasting the exact hash.
- Secret patterns apply whatever the device's `strip_volatile` setting is.
- Cisco IOS starts with SNMP communities, `username ... secret|password`, `enable secret|password`, `key 7`, TACACS+ and RADIUS keys, ISAKMP and IKEv2 pre-shared keys, and BGP neighbour passwords; MikroTik with the `password=`/`secret=`-style export properties. Each driver owns its list.

**Searching.** `POST /api/search/` `{q, mode, device_group?, driver?}`, with `HasDeviceGroupPermission('view_contents')`. It is a POST because a query can hold a secret, which must not appear in a URL (access logs, browser history). The query joins `access.devices_for(user, 'view_contents')`, so hidden devices neither appear nor count. Modes:
- `text`: case-insensitive substring, at least 3 characters (the trigram index needs them). The query goes through each driver's secret patterns (per driver, since their patterns differ) and searches that driver's documents with the result. A whole line with its secret in it therefore matches: `snmp-server community public RO` finds the devices. A secret matches only when typed in full, and case-sensitively.
- `regex`: RE2 syntax (`google-re2`, linear time, so a query cannot hang the API), matched per line, case-insensitive by default. PostgreSQL first narrows the candidates with `~*` in newline-sensitive mode (`(?n)`) under the statement timeout, after translating the RE2 spellings it lacks (`\b`, `\A`, `\z`, named groups); a pattern it still rejects is not pre-filtered. RE2 then decides which lines match, and a pattern RE2 rejects is a 400. Tokens are part of the text, so `snmp-server community \S+ RW` works; secret values themselves cannot be matched by a regex.
- `secret` (phase 17): the user types a value, the orchestrator tokenises it, and the search returns every line holding that token, on any driver. This finds reuse: "which devices still have the old TACACS key". A value that is itself a Cisco type 7 string is also looked for as its plaintext. Values are hashed unquoted (MikroTik quotes values with spaces), so the value is typed as the device was configured with it. The reply does not echo the value, and the page keeps it only while it is open.

Every search runs under a statement timeout (`SET LOCAL statement_timeout`, 5 s; on SQLite, which has none, the line matching stops after 10 s) and returns at most 200 devices. Each device comes with its name, group, driver, backup time and job id, the number of matching lines, and up to 20 of them (line number and text, tokens included).

**Audit.** Every search is recorded (`search.query`: mode, filters, the number of devices matched and their ids, since results show configuration lines as content views do). A text query is recorded in its tokenised form, so a secret typed into it is not written to the log. A secret search records neither the value nor its token.

**Saved searches (phase 17).** `SavedSearch`: owner, name, query, mode, filters (device group, driver), at `/api/saved-searches/` (`IsAuthenticated`, a queryset of the user's own, names unique per user, validated like a search, and only device groups the user can see). They are private to their owner and run on demand, a seed for compliance rules (ROADMAP D2). Secret searches cannot be saved, since that would store the value or a token that goes stale at key rotation.

**Frontend.** A Search page, shown when `GET /api/auth/user/` reports `config_search` and the user holds `view_contents` somewhere. The last search is kept in memory (a Pinia store, cleared at sign-out), never in the URL or browser storage, so going back from a backup shows the same results. It has a query box, a mode switch (Text, Regex, and Secret with a password input), and group and driver filters. Results are grouped by device, with matching lines and tokens shown as a "secret" chip; each line links to the backup view at that line (`?view=<job>&line=<n>` on the device's backups page). Phase 17 adds a saved-search list beside it.

### 7.3 Dashboard (phase 18)

The dashboard answers, for the devices the user can see: is collection healthy, is it getting better or worse, what is stale, what keeps failing, how much is stored, and (for global administrators) what the receivers refuse. Everything comes from rows that already exist (`BackupJob`, `Device`, `PushRejection`). There is no new model and no background aggregation: each card is a query run when the page asks for it.

**Endpoints** (`backups/dashboard.py`, under `/api/dashboard/`, replacing `dashboard-stats/` and `recent-backup-activity/`). Each card has its own endpoint, so a slow card does not hold up the others. Each states `IsAuthenticated` and filters with `access.devices_for(user, 'view')`, so hidden devices neither appear nor count. `days` is 7, 14, 30 or 90 (default 30).
- `summary/`: the existing tiles (devices by type; stored, failed and in progress in the last 24 h; average duration; device success rate).
- `activity/?window=1h|24h|7d`: recent jobs, as now.
- `trend/?days=`: one row per calendar day in the orchestrator's time zone, as now. Each row has stored and failed counts, the success rate, the average and longest request-to-stored duration, the average collection time, and the number of stored backups that changed (`changed=True`). It is one grouped query (`TruncDate` in the local zone) rather than one query per day, so 90 days costs the same as 7.
- `freshness/`: one row per device group the user can view (devices without a group form one more row). Each row has the number of enabled devices, how many were never backed up, how many have a latest *successful* backup older than 24 hours and older than 7 days, and the device whose successful backup is oldest (id, name, time). Rows are sorted stalest first. "Latest successful" is the newest stored job, not `Device.last_backup_status`, which a failure overwrites. The 24 h and 7 d thresholds are fixed; ROADMAP Q5 (stale detection) replaces them with each device's schedule.
- `failing/?days=&limit=10` (at most 50): the devices with the most failed or timed-out jobs in the window. Each row has its failed and stored counts, when it last failed and last succeeded, the latest error (first 200 characters, as already shown to `view` in the job list), and `recovered` when its newest finished job succeeded.
- `storage/?days=`: one row per storage target holding backups of devices the user can view. Each row has the number of stored, unpruned backups, the sum of their `size_bytes`, and how much of that was added in the window. Target names are already readable by every user (`IsGlobalAdminOrReadOnly`). The figure is the logical size the collector reported; targets that deduplicate or compress (git, some S3 setups) use less on disk, and the card says so.
- `push-refusals/?days=`: **global administrators only** (403 for others). Refusals have no device, so no device-group grant covers them, and the per-receiver list is already admin-only. It returns daily counts by reason, and the top 10 source addresses with their latest reason and receiver. Receivers rate-limit refusal reports, so the counts are a lower bound, and the card says so. To make a 90-day trend possible, `PushRejection` rows are kept by age (90 days, at most 5000 per receiver) instead of the newest 200.

A migration adds an index on `BackupJob (state, finished_at)` for the trend, failing and storage queries; freshness uses the existing `(device, -created_at)` index. That is enough for a few thousand devices over 90 days. A daily rollup table can be added if an estate outgrows it.

**Frontend.** The Dashboard page keeps the tiles and the activity feed, and gains a page-wide period selector. The period is kept in the URL (`?days=30`), so a view can be shared. New cards:
- Backups per day: stored and failed columns, stacked.
- Success rate: a line, on its own axis (no dual-axis charts).
- Duration: average and longest per day.
- Changes per day.
- Freshness: a table per group, linking the stalest device to its backups.
- Top failing devices: a table linking to each device's backups, with the latest error as a tooltip.
- Storage by target: horizontal bars.
- Push refusals: global administrators only. Bars by reason plus the top sources.

Charts are small in-house components (`components/charts/`): `TimeSeriesChart` draws lines or stacked columns on a daily axis in SVG, and `BarList` draws horizontal bars in HTML. They replace the canvas `SuccessChart`. Their colours are `--chart-*` theme variables, checked for colour-blind separation in both themes (stored and failed are blue and red, since green and red are not separable). They show values on hover and on keyboard focus (arrow keys), and carry a hidden table of every value. Each card loads separately and shows its own loading, empty and error states; a reload dims the previous figures rather than blanking them. The activity feed keeps polling as now. The `DashboardLayout` model, unused since the frontend rewrite, is removed together with the duplicate `core/dashboard_layout.py`.

### 7.4 Pins, labels and notes (phase 19)

Engineers mark known-good backups ("pre-upgrade 17.9", "approved baseline") and keep them whatever the retention policy says. Retention already leaves pinned backups outside the policy (decision 31). This phase lets people set the pin, a label and a note, and audits them. Pins are also what ROADMAP D3 (golden reference) will build on.

**Model.** `BackupJob` gains:
- `pinned_by` and `pinned_at`: who pinned it, and when.
- `label`: up to 64 characters, single line, blank by default.
- `note`: free text, at most 2000 characters.
- `annotated_by` and `annotated_at`: who last changed the label or note, and when.

**API.** The job list stays read-only. The two changes are separate actions because they need different grants and are audited differently:
- `POST /api/backups/{id}/pin/` `{pinned}` needs `HasDeviceGroupPermission('admin')`, because a pin overrides the group's retention policy (storage cost, and holding data the policy meant to delete). Only a stored backup can be pinned, and only while retention has not asked for its deletion, so a pruned backup gives 400. The check runs under `select_for_update` on the row. Retention claims rows under the same lock and re-checks `pinned`, so a pin and a deletion cannot both win. Unpinning is always allowed. The backup then rejoins its policy and may be deleted at the next pass that is not a dry run, so the UI asks first. A pinned backup also keeps an inactive device from becoming deletable (section 7.5).
- `POST /api/backups/{id}/annotate/` `{label, note}` needs `HasDeviceGroupPermission('view_contents')`, since a label describes the content. It works on any finished job, including failed and pruned ones: "device was being replaced" on a failure is useful, and a pruned job row stays as the record.
- The serializer adds `pinned_by_username`, `pinned_at`, `label`, `note`, `annotated_by_username` and `annotated_at`. Anyone with `view` sees them, as they see the rest of the job row. The list gains `?pinned=true` and `?labelled=true` filters.

**Audit.** `backup.pin` and `backup.unpin` record the device, the job and its label. `backup.annotate` records the new label and whether the note changed, not the note text. The audit log is not the place for free text that may grow to 2000 characters.

**Frontend.** On a device's backups page:
- A label appears as a chip beside the backup's time, and a note as an icon with the note in a tooltip.
- Group administrators get a pin/unpin action. Unpinning confirms with the retention warning.
- Users with `view_contents` get a "Label and note" action (`FormDialog`).
- A "Pinned only" toggle sits next to "Only changes".
- The compare page and the backup viewer show both backups' labels, and config search results show the label of the backup that matched.

### 7.5 Decommissioning devices (phase 20)

Devices are retired, replaced and removed, and nobody can delete one today. The API's `DELETE /api/devices/{id}/` (not offered in the UI) cascades to the device's job rows and leaves their stored content behind on the targets, with nothing left that points to it. Deleting on the spot is also wrong for the common case: after a device is retired, its last configuration is still needed for a while (rebuilding a replacement, audits, "what did the old core switch have?").

So removal takes two steps. **Mark inactive** stops all collection and starts a hold set by the device's retention policy. Once retention has removed every backup it is allowed to remove, the action becomes **Delete**, which removes the device row and its job history. A device with no stored backups (never backed up) can be deleted straight away. For the exceptions, such as a device added by mistake or a hold that must end now, a global administrator can **purge** an inactive device, which deletes its backups at once, pins included.

**States.** `active`, then `inactive` (holding backups), then `deletable` (inactive, and nothing retention could still remove). `deletable` is worked out from the device's backups, not stored:
- **Inactive**: `inactive_at` is set. The device is never collected: no schedule, no Backup Now, no pushes. Its backups stay readable, downloadable and comparable with the usual grants, and can still be pinned, labelled and annotated.
- **Deletable**: inactive, and no backup is stored, unpruned and on a target whose driver deletes, and no deletion is in flight (`prune_requested_at` set without `pruned_at`). Backups on targets that keep everything (git, decision 31) do not block deletion. They stay in that target's history, and the delete confirmation says so.

`enabled` keeps its meaning: a temporary pause of a device that is still in service. An inactive device ignores `enabled`.

**Model.** `Device` gains:
- `inactive_at` and `inactive_by`: when the device was marked inactive, and by whom.
- `inactive_reason`: up to 200 characters, optional ("replaced by core-sw-02").
- `purge_requested_at` and `purge_requested_by`: set when a global administrator purges the device.
- The unique constraint on `ip_address` becomes a partial one, applied only while `inactive_at` is null. A replacement usually takes over the old device's address, so it must not wait out the old device's hold. Inactive devices are never matched to pushes, so the receivers' match by source address stays unambiguous (decision 25). Reactivating a device whose address an active device now uses fails with 400.

`RetentionPolicy` gains `inactive_keep_days` (90 by default, nullable): how long an inactive device's backups are kept, counted from `inactive_at`. The migration sets existing policies to 90. Null means they are kept until someone acts: the device stays inactive until it is reactivated, given a policy that sets the field, or purged. A device with no retention policy behaves the same way. Nothing is deleted unless a policy or a purge says so.

**Retention.** `retention.plan` treats inactive devices differently:
- During the hold (`now < inactive_at + inactive_keep_days`), the policy applies as usual, including the `min_backups` floor. The newest backups survive the hold, so the device's final configuration is always there.
- After the hold, every stored, unpinned and unpruned backup has expired. The `min_backups` floor is lifted because the device will produce no new backups, and the floor exists to keep a current one.
- Everything else is unchanged. Pinned backups are never deleted, so a pinned backup keeps the device inactive until someone unpins it (the UI says which backups are holding it). A policy in dry run audits what would go and deletes nothing. The 1000-deletion cap per pass still applies. Deletions are confirmed by `deleted` events, as now (decision 30).

- A purged device has no hold, no floor and no pins left (the purge removed them), and dry run does not apply: every stored, unpruned backup has expired, whatever its policy, or with no policy at all. The purge itself sends the deletions (below), so the pass only picks up what it could not send, such as backups on a target with no worker online.

Retention never deletes the device itself. When the last deletion is confirmed, the device becomes `deletable` and waits for a person.

**API.** Deactivate, reactivate and delete need `HasDeviceGroupPermission('admin')`, as the permission matrix already says for disabling and deleting devices. They lock the device row (`select_for_update`):
- `POST /api/devices/{id}/deactivate/` `{reason}`: sets the inactive fields. A job that is already running finishes normally. If the device was push-enabled, the receivers get a new assignment without it (`push.service.bump_receivers`).
- `POST /api/devices/{id}/reactivate/`: clears them, and the purge fields too. The device goes back to its schedule, and the receivers get it back if it pushes. Backups that retention already deleted stay deleted, and deletions already requested still complete.
- `POST /api/devices/{id}/purge/` `{confirm}` needs `IsGlobalAdmin`: it ends the hold and removes pins, which overrides both the group's policy and its administrators' pins, so a group `admin` grant is not enough. `confirm` must equal the device name. The device must be inactive (400 otherwise), so a purge is always the second deliberate step. Under the row lock it sets the purge fields, unpins every pinned backup of the device, and claims all its stored, unpruned backups for deletion through `retention.request_deletion`, batched by target as retention does but not counted against the per-pass cap. Pinning a backup of a purged device gives 400.
- `DELETE /api/devices/{id}/`: allowed only when the device is `deletable` or has never had a stored backup. Otherwise it answers 409 with the reason (active, holding until a given date, held by N pinned backups, deletions in flight). The state is re-checked under the row lock, and the delete removes the device, its job rows and its `SearchDocument`.
- While a device is inactive, the API rejects edits to anything except `retention_policy` and `inactive_reason` (400). A device that is being kept should not be reconfigured.
- The device serializers add `inactive_at`, `inactive_by_username`, `inactive_reason`, `purge_requested_at`, `purge_requested_by_username`, `lifecycle` (`active`, `inactive` or `deletable`), `held_until` (the end of the hold, or null when it has no end), `held_backups` and `held_bytes` (stored backups retention could still delete, and their size), `pinned_backups`, and `can_delete` (deletable, or never stored a backup). The list annotates the counts in one query. `?lifecycle=active|inactive|deletable` filters the list, and leaving it out returns every device.

**Effects elsewhere.**
- Scheduler, Backup Now and `create_job`: inactive devices are skipped or refused, with `JobError('the device is inactive')`.
- Push: `push_devices()` leaves inactive devices out, and the `events` re-check refuses a file from an inactive device with `device_changed`, as it does for a disabled one.
- Config search: search shows a device's current configuration, so a retired device's configuration would give wrong answers to "which devices still have…". Deactivating deletes the device's `SearchDocument`, and the catch-up pass skips inactive devices and rebuilds the document after reactivation.
- Dashboard: summary and freshness count active devices only. Activity, trend, failing and storage keep counting the device's jobs, because they describe history and the storage actually used, until the device is deleted (decision 37).
- Device groups, collection groups, credentials and storage targets that are referenced by inactive devices still cannot be deleted, as now. A target holding their backups stays protected until the device is deleted.

**Audit.** `device.deactivate` (with the reason), `device.reactivate`, and `device.delete`. `device.delete` keeps a snapshot, because the row is gone afterwards: name, address, group, driver, number of job rows, first and last backup, and the targets that still hold content that cannot be deleted. Refused deletes (409) are not audited, since nothing changed. `device.purge` records the device, how many backups and bytes were claimed for deletion, and each backup it unpinned (job, label, who had pinned it), so the pins are not lost silently. Retention's own audit entries record what its passes delete.

**Frontend.**
- Devices page: a lifecycle filter (Active by default, Inactive, All). Inactive devices get an "Inactive" badge and a tooltip with the reason, who marked them and when. In place of Disabled, the badge shows "Held until 23 Jan 2027", "Held by 2 pinned backups", "Kept (no policy limit)", "Purging (12 left)" or "Ready to delete".
- Group administrators get one action whose label follows the state: "Mark inactive" for an active device (a `FormDialog` asking for the reason and showing the policy's hold), "Delete" when the device is deletable or never stored a backup, and "Reactivate" on an inactive device.
- Delete confirms by asking for the device name to be typed. It names any backups that will stay in a git target's history.
- Global administrators also get "Purge backups now" on an inactive device that still holds backups. The dialog states how many backups and bytes go, lists the pinned ones with their labels, and asks for the device name to be typed.
- The device's backups page shows a banner while the device is inactive, with the hold and links to the pinned backups that are holding it. Backup Now and edit are hidden there.
- The retention policy form gains "Keep inactive devices' backups for (days)", 90 by default, which can be cleared to keep them indefinitely.

**Out of scope.** Deleting devices automatically when they become deletable. The device row and its job history are the last record of the device, so a person decides when they go.

### 7.6 API tokens and service accounts (phase 21)

Scripts, CI and monitoring systems need to call the API without a browser session (ROADMAP Q9). Monitoring (section 7.7) is the first consumer, so this phase comes first. A token never carries more than its user's rights, and a **scope** narrows it further.

**Model.** `accounts.ApiToken`:
- `user`, `name` (unique per user), `scopes` (a list, below), `expires_at`, `allowed_networks` (a list of CIDRs, empty for any address).
- `prefix` (8 characters, shown in lists and audit entries) and `digest` (SHA-256 of the secret). The secret is 32 random bytes, so a fast hash is enough. It is never stored and is shown once, at creation.
- `created_at`, `created_by`, `last_used_at`, `last_used_address`, `revoked_at`, `revoked_by`.

The token is `dvt_<prefix>_<secret>` (URL-safe base64). The fixed `dvt_` prefix lets secret scanners (GitHub, gitleaks) recognise a leaked one.

**Scopes.**
- `api`: the whole API as the user, except token and service-account management, sign-in, sign-out and password changes. A token can never mint or revoke tokens.
- `monitoring`: only the read-only `/api/monitoring/` endpoints (section 7.7), filtered by the user's `view` grants.
- `monitoring_platform`: adds the platform-health sections (workers, scheduler, storage targets, receivers) to `monitoring`. These are admin-only facts elsewhere in the API, so only a global administrator can grant this scope, and only on a service account's token.

**Service accounts.** A user with `is_service_account` (a new `accounts.UserProfile` field) cannot sign in by any provider or password, has no session, and exists only to own tokens. Only global administrators create, edit and delete service accounts and their tokens. A service account joins user groups like any user, so its device-group grants come from the same matrix (decision 14). A service account cannot be a member of a global-administrator group: a leaked automation token must not be an administrator. A person's own tokens stop working when the person is deactivated. A service account's tokens don't, which is the reason service accounts exist.

**Authentication.** `accounts.authentication.TokenAuthentication` reads `Authorization: Bearer dvt_...`, runs before session authentication, and needs no CSRF token, because the browser does not send it on its own. A request is refused (401, with the same body for every cause) when the token is unknown, revoked or expired, its user is inactive, or the source address is outside `allowed_networks`. The source address is the one the audit log already uses (nginx's `X-Real-IP`). `last_used_at` and `last_used_address` are written at most once a minute, so polling does not mean a database write per request.

**Scope enforcement.** Each view declares `token_scopes` (default `('api',)`; the monitoring views declare `('monitoring', 'api')`). A token request to a view whose `token_scopes` doesn't overlap the token's scopes gets 403. The existing test that every view states its `permission_classes` also checks that every view resolves `token_scopes`.

**Limits.** Expiry is required: the default is 90 days, the longest is `DV_API_TOKEN_MAX_DAYS` (365). Service-account tokens may go up to the same limit. Each token is rate-limited (`DV_API_TOKEN_RATE`, 600/min by default, counted in Redis so every node shares the count) and answers 429 over it. At most 20 live tokens per user.

**Audit.** `token.create` and `token.revoke` record the token's prefix, scopes, networks and expiry. `token.use` is recorded the first time a token is used from an address it has not used before, not on every request (a Zabbix poll would flood the log). Refused token requests are recorded as `token.refused` (prefix if one parsed, cause, address), rate-limited per address as push refusals are. Every other audited action done through a token records the token's prefix next to the user.

**API.** `/api/tokens/` (`IsAuthenticated`, session only): the user's own tokens. List, create (returns the secret once) and revoke. `/api/service-accounts/` and `/api/service-accounts/{id}/tokens/` (`IsGlobalAdmin`): service accounts, their group memberships, and their tokens. `/api/admin/tokens/` (`IsGlobalAdmin`): every live token, revocable.

**Frontend.** An "API tokens" tab on the user's profile page: list, a create `FormDialog` (name, scopes, expiry, networks) and a show-once dialog with a copy button. An admin "Service accounts" page: accounts, their groups, and their tokens. Service accounts are hidden from the Users page and shown with a badge in group membership lists.

### 7.7 Monitoring: Zabbix and Prometheus (phases 22-24)

Backup health belongs in the monitoring system an estate already runs (ROADMAP Q4). DeviceVault serves read-only JSON that Zabbix polls with **HTTP agent** items, plus a Prometheus exposition of the same numbers, and ships Zabbix templates for both uses:
- **The DeviceVault host.** One Zabbix host represents DeviceVault: estate and per-group backup outcomes, freshness and platform health. It polls the orchestrator's web endpoints.
- **Existing device hosts.** A template linked to the hosts Zabbix already has (Router_X) adds that device's backup status, matched on its address. It polls a **receiver in the device's own zone** (the monitoring relay, below), not the orchestrator.

An HTTP agent item runs on whichever Zabbix server or proxy monitors its host. The proxies that monitor routers and switches sit in the device zones, and usually cannot reach the zone where the orchestrator lives. That is the same reason collectors exist. So per-device data is relayed:
1. The orchestrator publishes a signed snapshot to Redis every 15 minutes.
2. Receivers, which are already deployed in device zones and built to accept inbound connections (decision 23), load it and answer the proxies' requests.

Data can be up to one publish interval plus one poll interval old (about 30 minutes at the defaults). That is acceptable when backups run daily. The DeviceVault host itself is assigned to the server or a proxy that can reach the web tier.

Nothing is outbound from DeviceVault to Zabbix, and nothing Zabbix-specific runs in collectors. No Zabbix agent is needed for any of this. An agent on the orchestrator machines remains useful for operating-system metrics through Zabbix's stock Linux template, which is outside this design.

#### Failure reasons and freshness (phase 22, prerequisites)

**Failure reason.** `BackupJob.failure_reason`, nullable and indexed with `state`, takes one of:
- `connection`: unreachable, refused, or DNS.
- `auth`: login or enable refused.
- `timeout`: the device stopped answering mid-session.
- `command`: the device rejected a command.
- `verification`: reserved for ROADMAP Q12.
- `storage`: the storage worker failed.
- `integrity`: hash mismatch.
- `push`: reserved. A pushed file that cannot be ingested is refused (a `PushRejection`), not a failed job, so nothing sets it today.
- `orphaned`: the orchestrator's timeout fired.
- `unknown`.

The names are shared through `devicevault_protocol.jobs` (`FAILURE_*`, `failure_reason()`). How each side fills it in:
- **Workers.** `DriverError` (and so `TransientError` and `PermanentError`) gains a `reason` argument. `NetmikoDriver` maps Netmiko's authentication exceptions (and a refused enable or missing credential) to `auth`, network and SSH errors before the session is up to `connection` and after it to `timeout`, and output matching its `rejected_output` patterns (checked in the first lines of each command's output) to `command`. Unclassified exceptions report `unknown`. The reason travels in the signed `failed` job event (`protocol.jobs`).
- **Orchestrator.** It sets `integrity`, `orphaned` and `storage` itself, and maps any value it doesn't recognise to `unknown`.
- **Old jobs** keep null, which the metrics count as `unknown`.

`error` stays as it is. Monitoring never exposes the error text, only the reason.

**Expected interval.** `backups/freshness.py` gives each device:
- `expected_interval`: the longest gap between its schedule's next eight runs (`Schedule.next_run_after`), so an uneven schedule (weekdays only) is judged by its longest wait, or null for a device with no enabled schedule (push-only or manual).
- `next_due_at`: the deadline for a successful backup: the latest success (or, never backed up, the device's new `created_at`) plus the interval × `DV_STALE_FACTOR` (1.5 by default).
- `overdue`: an active, enabled device with an interval that is past `next_due_at`. "Latest successful" is the newest `stored` job, as the dashboard's freshness card uses.

Disabled and inactive devices are never overdue. Push-only devices get no interval here. ROADMAP Q5 adds a per-device expected push interval, the UI and notifications on top of this module, and the dashboard's fixed 24 h and 7 d freshness thresholds switch to it then.

#### Metric catalogue and snapshot (phase 22)

**Catalogue.** `monitoring/catalogue.py` declares every metric once:
- its key, a flat field of one section entry (`success_ratio_24h`, read in Zabbix as `$.success_ratio_24h`), and name;
- its kind (`gauge`, or `counter` for monotonic values);
- its unit (`s`, `B`, `%`, `unixtime`, or none) and Zabbix value type (`float`, `int`, `text`);
- its scope (`estate`, `platform`, `group`, `device`, `worker`, `target`, `receiver`);
- an optional value map and a description;
- its Prometheus series name and labels, or none to leave it out of Prometheus (text fields, per-device figures).

Value-mapped states travel as numbers (`status_code`, `failure_reason_code`, `lifecycle_code`; booleans as 0 and 1), because Zabbix value maps map numbers; the catalogue's `VALUE_MAPS` give the codes, which are only ever appended to. Counts are never null; ratios and durations with nothing to measure are.

The JSON endpoints, the Prometheus renderer and the Zabbix template generator all read it. A test fails if an endpoint returns a key the catalogue lacks, or the reverse.

**Metrics.** Windows are 1 h, 24 h and 7 d. Lifetime counters count every job row that still exists (rows survive pruning, decision 30; deleting a device removes its rows, which a counter reset absorbs).
- **Outcomes** (estate and group): finished jobs by state (`stored`, `failed`, `timed_out`) per window and lifetime, success and failure ratio per window (null with no finished jobs), failures per reason per window, jobs queued and running now, and attempts beyond the first (retries) per window.
- **Timing** (estate and group, 24 h): average, median, 95th percentile and maximum of collect time, store time, queue wait (`started_at - created_at`) and end-to-end time (`finished_at - created_at`). Percentiles are computed in Python over the window's values, which stays bounded at a few thousand jobs a day.
- **Freshness** (estate and group): devices total, enabled, disabled and inactive. Never backed up, overdue, and in consecutive failure at 1+, 3+ and 5+. The age of the oldest latest-successful backup, the single most useful alert.
- **Change** (estate and group, per window): stored backups that changed, and lines added, removed and modified.
- **Volume** (estate, group, target): bytes stored per window, stored and unpruned backups held, and their total `size_bytes`.
- **Push** (estate and receiver, 24 h): files accepted, refusals by reason, and the time of the last push. Push-enabled devices with no push in 7 d (estate only, until Q5 gives each one its own interval).
- **Platform** (`monitoring_platform` scope only):
  - Workers by role and status, each with heartbeat age, version, and applied versus desired assignment version.
  - The scheduler: whether a leader holds the lease, the lease's remaining TTL, and the age of the last tick. The leader records a `dv:scheduler:last_tick` key in Redis each tick, a small addition.
  - Per storage target: online workers serving it, the last stored job, and `storage` failures in 24 h. Target checks run on demand (decision 11) and are not stored, so their result is not a metric, and free space is not known.
- **Self**: DeviceVault version, `payload_encryption`, server time (so Zabbix can alarm on clock skew), the time the snapshot was computed, and its age.
- **Device** (per device, `device/` only):
  - Identity: `found`, id, name, group, address, `enabled`, `lifecycle`.
  - Latest outcome: the latest job's state, or `never` or `running`; last attempt and last success time; seconds since the last success; last failure time and `failure_reason`; consecutive failures.
  - Freshness: expected interval, next due, overdue.
  - Latest successful backup: collect, store and total time, size, changed, and lines added, removed and modified.
  - History: backups held, pinned backups, push mode and last push, and the 7 d success ratio.

**Estate, group and platform sections.** These are computed by queries over job rows, as the dashboard's are (decision 37): one grouped query per section, run when asked. Each result is cached in Redis so polling stays cheap:
- **Key.** `dv:monitoring:<user>:<scopes>:<section>`.
- **Lifetime.** `DV_MONITORING_CACHE_SECONDS` (60 by default).
- **Stampede guard.** A `SET NX` lock makes one node compute while the others serve the previous value, or wait up to 5 s when there is none.

**Device snapshot.** Per-device data is published rather than computed on request.
- **When.** The scheduler leader publishes every `DV_MONITORING_PUBLISH_SECONDS` (900 by default), plus once at start-up.
- **Who for.** One snapshot is published per **relay owner**: each service account that holds a live `monitoring` token. Usually that is one account (`zabbix`). A second Zabbix instance, or a team that should see only its groups, gets its own account and so its own snapshot.
- **Contents.** The device metrics of every device the owner can view, keyed by id, with an index from active address to id. It also carries `published_at`, the publish interval and the owner's id.
- **Storage.** It is staged as a blob (`protocol.blobs`, chunked as backups are, roughly 600 bytes a device). A pointer key `dv:monitoring:relay:<owner>` records the blob, its SHA-256, `published_at` and a signature over all three, made with the orchestrator signing key (`core.signing`) that receivers already pin. A collector can write to Redis, but cannot forge a snapshot that silences every alert.
- **Lifetime.** Blobs and pointers expire after 3 × the interval, so a stopped publisher shows up as stale rather than as old data that looks fresh.
- **Swaps.** A new generation is staged before its pointer is swapped, so a reader never sees half a snapshot.
- **Not encrypted.** Device names, addresses and backup status are metadata that receivers already hold in part for push, and it contains no configuration, credentials or error text.

The orchestrator's own `device/` endpoint reads the same published snapshot, so the direct path and the relay path always give the same answer. A site whose proxies *can* reach the web tier may skip the relay.

Every query is filtered with `access.devices_for(owner, 'view')`, so a token sees exactly what its owner would see in the UI and nothing else.

#### Endpoints (phase 22)

Under `/api/monitoring/`, `GET` only, JSON (except `metrics`). Each view states `permission_classes = [CanReadMonitoring]`, a new class in `accounts/access.py`:
- Any authenticated user, through a session or a token with the `monitoring` or `api` scope.
- Platform sections need a global administrator's session or the `monitoring_platform` scope. Otherwise they are left out of the response, not refused, so one token works for both templates.

The class joins the permission-class test. Reads are not audited (token use is, section 7.6).

| Endpoint | Returns |
|---|---|
| `summary/` | Estate outcomes, timing, freshness, change, volume, push and self, as one object |
| `device-groups/` | `{"data": [{"id", "name", ...metrics}]}`, one entry per visible device group (devices without a group form an `"ungrouped"` entry): the shape Zabbix low-level discovery reads, and the per-group items in the same response |
| `device/?ip=<addr>&id=<id>` | One device, from the caller's published snapshot (service accounts only; 404 for other callers, who have none). `id` wins when non-empty, otherwise the active device with that `ip_address` (unique among active devices, decision 42). An unknown address and a device the owner can't see both return 200 `{"found": 0, "published_at": ..., "published_age": ...}`, so the response says nothing about devices outside the owner's grants. With no current snapshot it answers 503 `{"error": "stale"}`. The receiver relay serves the same contract |
| `workers/`, `storage-targets/`, `receivers/` | Platform lists for discovery (empty without the platform scope) |
| `zabbix/template/?version=6.0\|7.0` | The generated Zabbix template (phase 24) |
| `metrics` | Prometheus text exposition (below) |

**Prometheus.** `metrics` renders the estate, group, worker, target and receiver metrics from the same cached sections, in text exposition format 0.0.4 written by `monitoring/prometheus.py` (a few lines; no `prometheus_client` dependency and no process-global registry):
- Names are `devicevault_*`, with `storage_target`, `worker`, `receiver`, `state`, `reason`, `window` and `stage`/`quantile` labels. Device-group series are separate families, `devicevault_group_*` labelled `device_group`, so summing them never double-counts the estate series.
- **No per-device series**: cardinality must stay bounded, and per-device status belongs to the Zabbix device template.
- Outcome counters are true counters.
- Timing is exported as gauges per window and quantile (`devicevault_backup_duration_seconds{stage, window, quantile}`), not histograms. Histograms need cumulative buckets, which means a rollup this design deliberately avoids (decision 37).
- Bearer tokens work with Prometheus's `authorization` scrape setting.

`deploy/prometheus/devicevault-rules.yml` ships alert rules equivalent to the Zabbix triggers. A Grafana dashboard is left to ROADMAP D30.

**Frontend.** An admin "Monitoring" page beside Flower:
- the endpoint URLs for this installation;
- template downloads for Zabbix 6.0 and 7.0;
- a three-step setup (create a service account, give its group `view`, create a `monitoring` token);
- a preview of `summary/` as the signed-in global administrator sees it.

#### Monitoring relay on receivers (phase 23)

A receiver gains a third listener next to SSH and TFTP: a small HTTPS server (`devicevault_receiver.monitoring`, aiohttp) that answers `GET /device/?ip=&id=` (also `/api/monitoring/device/`, so a URL copied from the orchestrator works) from the published snapshot. It never touches the database, as receivers never do.

**Settings.** Receiver settings gain a `monitoring` section, travelling in the assignment like the rest (decision 26): enabled (off by default) and port (8443). It listens on the receiver's existing listen address, like SSH and TFTP; SSH and the relay may not share a port. Unlike SSH and TFTP, the port is opened only once the section is enabled. A receiver may run with only this listener enabled, as a pure relay in a zone with no pushing devices. Every enabled receiver serves every device in the snapshots it holds, just as every receiver accepts every push-enabled device (decision 25). So any receiver a proxy can reach will do.

**TLS.** The receiver generates a self-signed certificate (ECDSA P-256, ten years) on first start and keeps it in its state volume beside its identity keys (`relay_tls.crt`, `relay_tls.key`). Its SHA-256 fingerprint is reported in the receiver's signed heartbeat (`receiver.monitoring.certificate_fingerprint`) and shown on the Workers page. Zabbix HTTP agent items can verify a certificate against a CA but cannot pin a fingerprint, so the template turns *verify peer* off. Traffic is encrypted, but the relay is not authenticated to the proxy. That is accepted because what crosses is a token limited to the `monitoring` scope and to the proxies' networks, and read-only metadata. Certificates issued by your own CA are a follow-up (ROADMAP D30).

**Tokens.** The assignment carries, for every live `monitoring` token of a relay owner:
- the token's prefix and digest (never the secret);
- its expiry and `allowed_networks`;
- its owner's snapshot id.

Only live tokens of active service accounts are listed, and only to receivers with the relay enabled. The orchestrator re-sends receiver assignments (`push.service.receiver_inputs_changed`, which push-device changes also use) when a relay token is created or revoked, or when a service account is changed or deleted; the same changes ask the scheduler leader to publish the snapshots at its next tick (`dv:monitoring:publish-now`), so a new owner does not wait a whole interval. Expiry needs no message, since the relay refuses an expired token itself; the scheduler leader still re-sends assignments once a relay token's expiry has passed (one indexed query a tick), to keep the lists tidy. The receiver checks the bearer token against that list in constant time, enforces expiry and the network list (the source address comes from the socket), and gives every refusal the same 401. It rate-limits per token locally (`DV_API_TOKEN_RATE` travels in the assignment, not as a receiver setting), answering 429.

**Reporting.** Usage is reported back in a signed `monitoring.used` event every minute (Celery task `orchestrator.monitoring_event`; formats in `devicevault_protocol.monitoring`): per token, the request count and the source addresses seen. From these the orchestrator updates `last_used_at` and records first use from a new address (section 7.6), naming the receiver. Refusals are signed `monitoring.refused` events, at most one a minute per source address, and audited as `token.refused` with the receiver named. The `events` process checks each event's signature and that its sender is an approved receiver, as for push events. The heartbeat's `receiver.monitoring` carries the listener state, the certificate fingerprint, the snapshots loaded (generation, `published_at`, device count, stale) and request, refusal and throttle counts since start.

**Snapshot loading.**
- **Watching.** Every 30 seconds the receiver reads each owner's pointer key, with no blob fetch when the generation hasn't changed.
- **Loading.** On a new generation it fetches the blob and checks its SHA-256 and the signature against its pinned orchestrator key. Only then does it swap the in-memory index.
- **Bad snapshots.** One that fails verification is ignored, the previous one is kept, and a `monitoring.snapshot_rejected` event is raised (once per bad generation), which the orchestrator logs and audits.
- **Off the loop.** Redis reads and event sends run in threads (`asyncio.to_thread`), so requests are never held up by them.
- **Stale snapshots.** A snapshot older than 3 × its interval, or none at all, makes the receiver answer 503 `stale`, so the problem shows in Zabbix rather than data quietly ageing.
- **Cost.** Lookups are dictionary reads. 10,000 devices polled every 15 minutes is about 11 requests a second, spread over the zone's receivers.

**Frontend.** The receiver settings form gains the Monitoring endpoint section. The Workers page shows, for each receiver with it enabled: its URL, its certificate fingerprint, the age of the snapshots it has loaded, and its request and refusal counts.

#### Zabbix templates (phase 24)

**Generator.** `monitoring/zabbix.py` builds the templates from the catalogue. `manage.py zabbix_template --version 6.0|7.0` writes one file, and `make zabbix-template` regenerates both into `deploy/zabbix/devicevault_zabbix_6.0.yaml` and `devicevault_zabbix_7.0.yaml`. Both are committed, so changes show in review, and a test fails when either is out of step with the generator. The export format differs between the LTS versions (UUIDs, dashboard widget fields, some preprocessing names), so the generator has one small emitter per version over shared content. Template UUIDs are derived from stable keys (uuid5), so regenerating changes nothing that did not change. Templates do not depend on the installation (drivers and groups are discovered), so the endpoint serves the same output.

**`DeviceVault by HTTP`** is linked to one host that stands for DeviceVault.
- **Macros:** `{$DV.URL}`, `{$DV.TOKEN}` (secret text), `{$DV.INTERVAL}` (1m), `{$DV.SUCCESS.MIN}` (95), `{$DV.STALE.MAX}` (2d), `{$DV.FAIL.CONSEC}` (3), `{$DV.DURATION.MAX}` (10m), `{$DV.WORKER.HEARTBEAT.MAX}` (3m), `{$DV.PENDING.MAX}` (1h), `{$DV.SKEW.MAX}` (60).
- **Master items:** one HTTP agent item each for `summary/`, `device-groups/`, `workers/`, `storage-targets/` and `receivers/`, sending `Authorization: Bearer {$DV.TOKEN}`. Every value is a dependent item with JSONPath, and those that rarely change use *Discard unchanged with heartbeat*.
- **Discovery:** dependent LLD rules (supported since Zabbix 4.2) for device groups, workers, storage targets and receivers. Each has item and trigger prototypes and a *Keep lost resources* period of 7 days.
- **Triggers:**
  - Endpoint unreachable, or answering 401/403/5xx.
  - Snapshot older than 3 × `{$DV.INTERVAL}`.
  - Success ratio below `{$DV.SUCCESS.MIN}` over 24 h, per estate and per group.
  - Oldest latest-success age above `{$DV.STALE.MAX}`, per group.
  - Overdue devices > 0, and devices in `{$DV.FAIL.CONSEC}`+ consecutive failures > 0, per group.
  - Never-backed-up devices > 0.
  - p95 end-to-end duration above `{$DV.DURATION.MAX}`.
  - Platform: the scheduler has no leader, or its last tick is over 2 minutes old; a worker's heartbeat is older than `{$DV.WORKER.HEARTBEAT.MAX}`; a worker has been pending approval longer than `{$DV.PENDING.MAX}`; an assignment version is behind for 10 minutes; a storage target has no online worker; push refusals spike.
  - Clock skew above `{$DV.SKEW.MAX}` seconds.
  - Every trigger has a recovery expression and tags (`component`, `scope`, `group`). All depend on the endpoint trigger, so a DeviceVault outage raises one problem, not hundreds.
- **Also included:** value maps (job states, failure reasons, worker status, lifecycle) and a template dashboard (success ratio, duration percentiles, failures by reason, freshness per group, platform health).

**`DeviceVault Device by HTTP`** is linked to the device hosts Zabbix already has, so network teams see backup status on the host they already watch.
- **Match:** the master item calls `{$DV.RELAY.URL}/device/?ip={HOST.IP}&id={$DV.DEVICE.ID}`. `{HOST.IP}` is the host's default interface address, so linking the template is usually the whole setup. `{$DV.DEVICE.ID}` (empty by default) is set on a host whose interface address isn't the one DeviceVault backs up. Zabbix user macros cannot contain built-in macros, so the two are separate parameters rather than one macro with a default.
- **Relay:** `{$DV.RELAY.URL}` is a receiver in the zone of the proxy that monitors the host (`https://receiver-site-a:8443`). It is set once per zone on a small site template that links this one, or on the hosts themselves, since Zabbix has neither host-group nor proxy macros. Pointing it at `{$DV.URL}/api/monitoring` uses the orchestrator directly where the proxies can reach it. *Verify peer* is off (the relay's certificate is self-signed).
- **Credentials:** `{$DV.TOKEN}` is meant to be a global macro (or set on the site template). It may be the same `monitoring` token the DeviceVault host uses.
- **Polling:** `{$DV.DEVICE.INTERVAL}` (15m, matching the publish interval; polling faster gains nothing).
- **Items:** dependent items for every device metric. Last success and last attempt are `unixtime`. Durations are `s` and size is `B`. Status, reason and lifecycle use value maps.
- **Triggers:**
  - *Not backed up by DeviceVault*: `found=0 and {$DV.NOTFOUND.ALERT}=1`, severity Information. Zabbix trigger severity can't come from a macro, so a macro switches the trigger off instead. Linked across a whole host group, this shows which monitored devices nothing backs up.
  - *Backup overdue*: `overdue=1`.
  - *Backup failing*: consecutive failures >= `{$DV.DEVICE.FAIL.CONSEC}` (2).
  - *Authentication failing*: the latest reason is `auth`, severity Average, because credentials do not fix themselves.
  - *No successful backup for `{$DV.DEVICE.STALE.MAX}`*: 0 by default, which switches it off. This is for estates that prefer a flat threshold to the schedule-based `overdue`.
  - *No data from DeviceVault*: `nodata` on the master item for 3 intervals, or the relay answering 503 `stale`. The other device triggers depend on it.
  - *DeviceVault data is old*: `published_at` older than `{$DV.DEVICE.DATA.MAX}` (45m), which catches a publisher that has stopped while a relay still serves.
  - Device triggers include `enabled=1 and lifecycle=active`, so a paused or retired device stays quiet. Zabbix cannot make a template trigger depend on a trigger of another host (the DeviceVault host), hence the per-host *No data* trigger.

**Validation.** `make zabbix-validate` starts Zabbix 6.0 and then 7.0 (server, web and PostgreSQL containers from `deploy/zabbix-test/`), and imports both templates through the Zabbix API (`configuration.import`). Then it creates one host per template, pointing the DeviceVault host at a stub server that serves recorded orchestrator responses, and the device host at a real receiver relay loaded with a recorded, signed snapshot. It checks that every item becomes supported and that the expected triggers fire. It is Docker only, like everything else. It is not part of `make check` (two Zabbix servers make CI slow). A separate `zabbix.yml` workflow runs it on pull requests that touch `monitoring/` or `deploy/zabbix/`, and it is not required to merge.

**Documentation.** A "Monitoring" section in `DEPLOYMENT.md` covers:
- creating the service account and token;
- importing the templates and setting the global macros;
- enabling the monitoring relay on a receiver in each proxy zone, the firewall flow (proxy to receiver on 8443), and the per-zone site template;
- linking the device template to an existing host group;
- tuning the thresholds;
- the Prometheus scrape configuration;
- the request rate the device template generates, and how stale its data can be (one publish plus one poll interval).

#### Out of scope

These stay in ROADMAP D30:
- pushing values out with `zabbix_sender` (trapper items) for Zabbix servers that cannot reach DeviceVault;
- RabbitMQ queue depth (it needs the management API and its credentials);
- Redis and broker reachability, and key and certificate expiry;
- the `events` backlog;
- creating Zabbix hosts from DeviceVault's inventory;
- relay certificates issued by your own CA (the relay's certificate is self-signed in phase 23);
- a Grafana dashboard.

A bulk per-device endpoint is also left out: the device template's per-host poll replaces it, and per-device Prometheus series are refused by design.

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
| 14 | `feat/retention` | Retention enforcement (ROADMAP Q1): policy limits plus an always-kept minimum and dry run, the scheduler's retention pass, signed `storage.delete` tasks and deletion events, `deletes` driver capability, policy preview and audit, the `pinned` flag that Q8 builds on, UI | yes |
| 15 | `feat/change-summary` | Change summary on every backup (ROADMAP Q3): compared with the device's previous backup after decrypting and dropping the driver's volatile lines; `changed`, lines added and removed; backfill command; `?changed=` filter; Changes column and "Only changes" filter in the UI | yes |
| 16 | `feat/config-search` | Config search (ROADMAP Q6, section 7.2): `search` app and `SearchDocument`; `secret_lines` and encodings in the driver framework (Cisco IOS and MikroTik patterns, `cisco7`), validated in the catalogue; tokens keyed from the data key; indexing in the post-store task; the scheduler's catch-up pass and `reindex_search`; PostgreSQL (`pg_trgm`) and SQLite backends; text and regex search with RE2, timeouts, caps and audit; `DV_CONFIG_SEARCH`; Search page. The search backend tests also run against PostgreSQL in `make check` | yes |
| 17 | `feat/secret-search` | Secret search mode (audited without the value) and private saved searches, with their UI | yes |
| 18 | `feat/dashboard` | Dashboard upgrades (ROADMAP Q13, section 7.3): per-card `/api/dashboard/` endpoints (summary, activity, trend, freshness, failing, storage, push refusals for global admins); one grouped query per trend; `(state, finished_at)` index; push refusals kept by age; in-house SVG chart components replacing the canvas chart; page-wide period in the URL; dead `DashboardLayout` removed | yes |
| 19 | `feat/backup-pins` | Pin, label and annotate backups (ROADMAP Q8, section 7.4): `pin/` (group `admin`, locked against retention) and `annotate/` (`view_contents`) actions, who and when, `?pinned=`/`?labelled=` filters, audit, UI on the backups, compare and search pages | yes |
| 20 | `feat/device-decommission` | Decommissioning devices (section 7.5): Mark inactive (who, when, reason), a hold set by the new `RetentionPolicy.inactive_keep_days` (90 days by default), retention lifting the `min_backups` floor once the hold ends, Delete only when nothing deletable remains (409 otherwise), global-admin purge (unpins, deletes at once, audited), the IP address unique among active devices only, inactive devices left out of scheduling, push, search and the dashboard device counts, audit with a snapshot on delete, lifecycle filter and actions in the UI | yes |
| 21 | `feat/api-tokens` | API tokens and service accounts (ROADMAP Q9, section 7.6): `ApiToken` (hashed, shown once, expiring, network allow-list), `api`/`monitoring`/`monitoring_platform` scopes and per-view `token_scopes`, bearer authentication without CSRF, per-token rate limit, service accounts (no sign-in, never global administrators), audit of create, revoke, first use per address and refusals, profile tokens tab and Service accounts page | yes |
| 22 | `feat/monitoring-api` | Monitoring endpoints (ROADMAP Q4, section 7.7): `BackupJob.failure_reason` set by workers and the orchestrator, `backups/freshness.py` (expected interval, overdue), metric catalogue, cached estate, group and platform sections, the signed per-relay-owner device snapshot published by the scheduler leader every 15 minutes, `summary/`, `device-groups/`, `device/`, platform lists, `CanReadMonitoring`, Prometheus `metrics` and alert rules, scheduler last-tick key, Monitoring admin page | yes |
| 23 | `feat/monitoring-relay` | Monitoring relay on receivers (section 7.7): opt-in HTTPS listener with a self-signed certificate and reported fingerprint, relay tokens (digests) in the receiver assignment and re-sent on token changes, snapshot loading with signature and hash checks, 503 when stale, `monitoring.used`/`refused`/`snapshot_rejected` events, receiver settings and Workers page UI | yes |
| 24 | `feat/zabbix-templates` | Zabbix templates (section 7.7): catalogue-driven generator for 6.0 and 7.0, `DeviceVault by HTTP` and `DeviceVault Device by HTTP` (polling the zone's relay) committed under `deploy/zabbix/` with a drift test, `zabbix/template/` endpoint, `make zabbix-validate` against Zabbix 6.0 and 7.0 containers and its workflow, DEPLOYMENT.md monitoring guide | yes |
| later | — | New vendor drivers, Redis Sentinel | — |

Candidate work beyond these (notifications, change summaries, compliance checking, restore, integrations and more, ranked as quick wins and larger changes) is collected in [ROADMAP.md](ROADMAP.md); an item gets a phase here once it is scheduled.

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
| 7 | No CI for now (no GitHub Actions minutes). A CI-agnostic `Makefile` is ready for a future GitLab or Gitea pipeline. Superseded by decision 29. |
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
| 29 | The repository is public, which makes GitHub Actions free. `ci.yml` runs `make check` on every pull request and is required to merge to `master`. Pushing a `vX.Y.Z` tag runs `release.yml`, which checks the tag against the `VERSION` file, runs `make check`, publishes signed multi-arch images to GHCR and creates the GitHub Release. `VERSION` is the single source of the release version; `make set-version` copies it into each package, and a test fails if any package disagrees. |
| 30 | (phase 14) Retention keeps the job row and marks it pruned (`prune_requested_at`, then `pruned_at` when the storage worker confirms), so history, dashboard counts and the audit trail survive; content is refused as soon as deletion is requested. A failed deletion clears the request and a later pass retries; an unanswered one is re-sent after a day (deleting is idempotent). Deletion events are accepted only for a requested deletion and from a worker serving that backup's target. |
| 31 | (phase 14) Safety rails: the newest `min_backups` (at least 1) are always kept, **pinned backups are outside the policy** (neither counted towards its limits nor deleted, so pinning does not shorten the history of the rest), new policies start in dry run (audited when the would-delete set changes), at most 1000 deletions per pass, and targets whose driver does not declare `deletes` (git) are left alone rather than rewriting history. `pinned` lands with retention; Q8 adds setting it, labels and notes. |
| 32 | (phase 15) Change summaries are computed in the orchestrator, the only place that can decrypt, by a signed internal task on its own queue (workers can publish there too) run by `events`, not inline in the job event, so a slow read never holds up event handling. It reads both backups back through the storage worker (two request/response reads; two unencrypted backups with equal hashes are unchanged without reading). Collectors advertise `volatile_lines`; the orchestrator bounds and validates them (they run on its side) and applies the device driver's patterns unless the device turned `strip_volatile` off. Binary backups are compared for equality only, backups over 16 MiB are not compared, and the first backup of a device counts every line as added. |
| 33 | (phase 16) Config search indexes in the **orchestrator database** (PostgreSQL `pg_trgm`; an unindexed scan on SQLite), not a separate engine. Searches are substrings and regexes of literals that word-based full-text search mangles; an indexed-only field in Solr or OpenSearch still holds every term and its positions in plaintext; and one database keeps the permission check inside the query. The backend is an interface, so an external engine can be added later. |
| 34 | (phase 16) Search is **opt-in** (`DV_CONFIG_SEARCH`) and covers only each device's **latest** backup: one `SearchDocument` per device, built by the post-store task from bytes it already decrypted, so no backup is read twice. A catch-up pass in the scheduler builds missing or stale documents, so enabling search, key rotation and driver upgrades need no manual step. |
| 35 | (phase 16) Secret values are replaced by **keyed tokens** before indexing: drivers declare `secret_lines` (with optional encodings the orchestrator reverses, such as `cisco7`), and each value becomes an HMAC whose key is derived from the data key and never stored in the database. Queries are tokenised by the same patterns on the server, so a full line or a bare secret value (phase 17) still finds its devices, while a dump shows only which devices share a secret, which is accepted. Secret values cannot be matched by substring or regex. |
| 36 | (phase 16) Regex search uses RE2, matched per line, so a user's pattern runs in linear time; PostgreSQL only narrows the candidates, under a statement timeout. Results are capped, and searches are audited with secrets in tokenised form. |
| 37 | (phase 18) Dashboard figures are **computed on request** from job rows, one endpoint per card, filtered by `access.devices_for(user, 'view')`. No rollup table and no scheduled aggregation: the data is small at the expected scale, and a rollup would be a second copy to keep consistent with retention and device deletion. Push refusals are shown to global administrators only, since they belong to no device group. |
| 38 | (phase 18) Charts are **in-house components** (SVG time series, HTML bar lists), not a charting library. The dashboard needs only daily lines, bars and horizontal bars. SVG follows the theme through CSS variables, gives hover and keyboard values and a text alternative without extra work, and adds no dependency to keep pinned. |
| 39 | (phase 19) Pinning needs the group's **`admin`** grant, because it overrides that group's retention policy. Labels and notes need **`view_contents`**, because they describe content. They are separate actions with separate audit entries. Pinning takes the same row lock as retention's deletion claim, so a backup is never both pinned and deleted. |
| 40 | (phase 20) Devices are removed in two steps. **Mark inactive** stops collection and starts a hold. **Delete** removes the device and its job rows, and is allowed only once retention has removed every backup it may remove (or the device never stored one). Only a person deletes a device; retention never does. A global administrator can **purge** an inactive device to end its hold early: it unpins and deletes every backup at once, needs the device name typed, and is audited with the pins it removed. A group `admin` cannot, since a purge overrides the group's policy and pins. Backups on targets that keep everything (git) do not block deletion and stay in their history. |
| 41 | (phase 20) The hold is a retention policy setting, `inactive_keep_days` (90 days by default), counted from when the device was marked inactive. During the hold the policy applies as usual, `min_backups` included. Afterwards the floor is lifted and every unpinned backup expires. With no value, or no policy, backups are kept until someone acts (reactivates, sets a policy, or purges). Pinned backups keep a device inactive until they are unpinned. |
| 42 | (phase 20) `Device.ip_address` is unique among **active** devices only, so a replacement can take over its predecessor's address during the hold. Inactive devices are never matched to pushes, so decision 25 still holds. Reactivating a device whose address is taken fails. |
| 43 | (phase 21) API tokens are built before monitoring and serve both: one token system, with **scopes** (`api`, `monitoring`, `monitoring_platform`) narrowing what a token reaches, never widening its user's grants. Secrets are 32 random bytes stored as SHA-256 (a slow hash adds nothing at that entropy), prefixed `dvt_` for secret scanners, expiring (365 days at most) and optionally limited to source networks. |
| 44 | (phase 21) Machine access uses **service accounts**: users that cannot sign in, managed by global administrators, granted through user groups like anyone else, and never members of a global-administrator group. Token use is audited on first use from each address and on refusal, not per request, so polling does not flood the log. |
| 45 | (phase 22) Monitoring is **pull only**: Zabbix HTTP agent items and a Prometheus scrape read `/api/monitoring/`, and DeviceVault opens no outbound connection. Zabbix trapper push is a later transport over the same catalogue (ROADMAP D30). |
| 46 | (phases 22-23) Per-device status reaches **existing Zabbix hosts** through a template linked to them, polling `device/` once per host and matched on `{HOST.IP}` (overridable by `{$DV.DEVICE.ID}`), not through host prototypes that would duplicate the inventory. The proxies that monitor devices usually cannot reach the orchestrator's zone, so they poll a **receiver relay** in their own zone. The scheduler leader publishes a **signed** device snapshot to Redis every 15 minutes, one per relay owner (each service account with a `monitoring` token), and receivers verify it against the pinned orchestrator key and answer from memory. Up to about 30 minutes of staleness is accepted, since backups run daily. Estate, group and platform metrics still come from the orchestrator directly. An unmatched or invisible device answers `found: false`, and the template turns that into a coverage alarm. |
| 47 | (phase 22) Failures carry a structured **`failure_reason`** set by workers (`DriverError(reason=...)`, in the signed event) and the orchestrator. Monitoring exposes the reason only, never the error text, which can hold device output. |
| 48 | (phase 22) "Overdue" is computed by DeviceVault from each device's schedule (`backups/freshness.py`, the base Q5 builds on), and raw ages are exported too, so the templates alarm on the schedule-aware flag and a flat threshold remains available. Push-only devices have no expected interval until Q5. |
| 49 | (phase 22) One **metric catalogue** feeds the JSON endpoints, Prometheus and the Zabbix generator. Prometheus gets no per-device series, and durations are window quantile gauges rather than histograms, since histograms need the rollups decision 37 avoids. |
| 50 | (phase 23) The relay is a receiver listener, not a new component: receivers are the part already built and deployed to accept inbound connections in device zones. It is opt-in per receiver, serves every device in the snapshots it holds, and uses a **self-signed certificate** (Zabbix cannot pin one, so *verify peer* is off). That is accepted because only a `monitoring`-scoped, network-limited token and read-only metadata cross it. Receivers learn relay tokens as digests in their assignment and report use and refusals as signed events. |
| 51 | (phase 24) Zabbix templates are **generated and committed** for 6.0 and 7.0 LTS, with a drift test, and validated by importing them into real Zabbix containers (`make zabbix-validate`, its own workflow, not part of `make check`). |
