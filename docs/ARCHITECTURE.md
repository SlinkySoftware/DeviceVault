# DeviceVault — Target Architecture & Delivery Plan

Status: **Agreed** (2026-10-23). Decisions on the former open questions are recorded in section 11.

## 1. Goals

1. Hard separation between the **infra layer** (DB, RabbitMQ, Redis), the **orchestrator**, and **workers**. Each deploys independently.
2. Workers hold **no configuration** beyond the RabbitMQ and Redis endpoints (plus TLS CA). They register, wait for admin approval, and receive their role, queues, and config from the orchestrator.
3. Storage is configured **per storage target**, assigned to specific workers, not per storage type.
4. The UI stores Flower endpoints and gives admins direct access to them.
5. Collector drivers and storage drivers are pluggable. New device platforms and storage backends (including an arbitrary database) are additive, not invasive.
6. Current stacks: Python 3.14 (verified: Django 6.1.2, Celery 5.6.3, psycopg 3, djangosaml2/xmlsec, python-ldap, netmiko, scrapli, flower all install and run), Node 24, Quasar 2.35 / Vue 3.5 / vue-router 5 / Pinia 4. Docker is the only deployment target.

Sizing assumptions: 6–8 collectors, 2–4 storage workers, backups from hundreds of KB up to tens of MB.

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
```

No component talks to another directly. Everything goes over AMQP or Redis.

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
protocol/        shared package: queue/exchange names, message schemas (pydantic), envelope crypto
orchestrator/    Django project + apps (pyproject, depends on protocol)
worker/          Celery worker runtime + drivers (pyproject, depends on protocol)
frontend/        Quasar/Vue SPA (TypeScript)
docker/          Dockerfile (targets: orchestrator, worker, dev), web.Dockerfile, entrypoints, nginx template
deploy/
  infra/         compose: postgres, rabbitmq, redis (+ example HA notes)
  orchestrator/  compose: web, api, events, scheduler, flower(profile)
  worker/        compose: worker (env: DV_BROKER_URL, DV_REDIS_URL, DV_TLS_CA?, DV_WORKER_NAME?)
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

Retries: drivers raise typed errors. Transient errors (timeout, connection refused, lock held) trigger a Celery retry with backoff. Permanent errors (auth failure, unknown driver) fail the job. Each job is handled exactly once, keyed on `job_id`. Binary/text is carried as job metadata end to end, which fixes the dropped `is_binary` flag.

## 6. Data model (main changes)

- `Worker` (replaces `WorkerRegistration`): id, name, status (pending/approved/revoked), role, public keys, capabilities, assignment version applied/desired, last_seen.
- `CollectionGroup`: queue `collector.group.<uuid>`, M2M workers. The UI warns when a device's driver isn't supported by every approved member.
- `StorageTarget` (replaces `BackupLocation`): name, driver key, config (validated against the driver schema, secret fields encrypted), M2M workers, queue `storage.target.<uuid>`. Assigning a non-`shareable` driver (local fs, local git) to more than one worker is blocked.
- `Device`: `driver` + `driver_params` (validated against the driver schema), collection_group, storage_target, credential, schedule (FK; currently missing, which is why schedules never fire), retention_policy.
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

Push mode (future): a driver may declare `mode="push"` with a listener (TFTP/SCP/SFTP). The orchestrator assigns listeners to collectors, and the collector maps the inbound source IP to a device via the assignment. The interface is reserved now and not built.

**Storage driver** (`worker/storage/drivers/`): `store(data, name, params) → ref`, `read(ref, params) → bytes`, `delete(ref, params)`, `check(params)`, plus `Params`, `shareable`. Drivers (phase 6): filesystem and git (paths relative to the worker's `/srv/devicevault` volume, not shareable) and S3 (shareable); PostgreSQL (shareable, psycopg 3, one `bytea` row per backup in `<schema>.devicevault_backups`, with discrete connection and TLS settings). Other databases get drivers of their own rather than a generic SQLAlchemy URL, since TLS and connection settings differ for each.

Drivers are discovered through Python entry points, so a new driver can ship as a separate package without editing core.

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
| later | — | Retention enforcement, push collection, new vendor drivers, external auth, Redis Sentinel | — |

Each backend phase ships its own UI changes, so master never has a broken frontend.

## 11. Decisions log

| # | Decision |
|---|---|
| 1 | Orchestrator signing key is TOFU-pinned by workers at first assignment; recovery is a worker state reset. |
| 2 | Payload encryption is a **global orchestrator option**: off for development, on per deployment (see 4.3). |
| 3 | Redis streams dropped. Events go over RabbitMQ, and payloads are staged in Redis as blobs. |
| 4 | Infra HA and the front-end VIP/LB are documented, not shipped in compose. |
| 5 | Config comes from env and Docker secrets only; no `config.yaml`. SQLite→Postgres migration is a `manage.py` command. |
| 6 | External auth (LDAP/SAML/Entra) deps removed; external auth becomes a later phase. |
| 7 | No CI for now (no GitHub Actions minutes). A CI-agnostic `Makefile` is ready for a future GitLab or Gitea pipeline. |
| 8 | (phase 5) Secrets in transit are sealed per recipient worker rather than to collection-group keys: simpler, no key distribution or re-keying on membership change, and cheap at the expected 6-8 collectors. The vault public key and the payload-encryption switch travel in each signed task rather than in assignments. |
| 9 | (phase 5) Collector drivers use Netmiko for SSH CLI platforms; Scrapli can be added as a second base when a platform needs it. |
| 10 | (phase 6) Storage target settings travel in each signed storage task (sealed to the target's workers) rather than in assignments, for the same reason as decision 8: workers keep no configuration state. Assignments carry only queues. Jobs protect their storage target from deletion, and a target's driver is fixed once it holds backups. |
| 11 | (phase 6) Reads and target checks are request/response tasks answered through the Celery result backend, not `read.result` events: the API needs the answer within the same HTTP request, which an event handled by any `events` process cannot give it. The content itself still travels through Redis, checked against the job's recorded SHA-256. |
| 12 | (phase 7) A proxied Flower is authorised by a short-lived signed cookie, scoped to `/flower/<slug>/` and bound to the user's API token, that the UI requests before opening it: the SPA's token lives in browser storage, which a new tab doesn't send. The API names the upstream in the `auth_request` response, so the nginx configuration stays static. |
| 13 | (phase 7) One database per message bus: `migrate` claims Redis for its database's installation id and a node with another database refuses to start. This enforces single-node SQLite and also catches nodes pointed at different PostgreSQL databases. |
| — | Retention enforcement: in scope, designed in a later phase. |
