# Deploying DeviceVault

DeviceVault ships as three images and three independent Compose stacks. The
stacks never talk to each other directly: orchestrators and workers connect
out to RabbitMQ and Redis in the infra stack, and that is all.

| Stack | Path | Runs |
|---|---|---|
| Infra | `deploy/infra` | RabbitMQ, Redis, PostgreSQL (optional) |
| Orchestrator | `deploy/orchestrator` | web (nginx + UI), api, events, scheduler, Flower (optional) |
| Worker | `deploy/worker` | one collector or storage worker per Compose project |

> **Status:** pre-release. See [ARCHITECTURE.md](ARCHITECTURE.md).

## 1. Build the images

```bash
make images IMAGE_TAG=0.1.0
# devicevault-orchestrator:0.1.0, devicevault-worker:0.1.0, devicevault-web:0.1.0
```

Push them to your registry and set `DV_ORCHESTRATOR_IMAGE`, `DV_WEB_IMAGE` and
`DV_WORKER_IMAGE` when running the stacks, or retag them as `:latest`.

## 2. Infra

```bash
cd deploy/infra
cp infra.env.example infra.env          # set the passwords
docker compose up -d                    # SQLite orchestrator
docker compose --profile postgres up -d # PostgreSQL orchestrator (required for HA)
```

Ports 5672 (AMQP), 15672 (RabbitMQ management), 6379 (Redis) and 5432
(PostgreSQL) are published. Override them with `DV_RABBITMQ_PORT`,
`DV_RABBITMQ_MANAGEMENT_PORT`, `DV_REDIS_PORT` and `DV_POSTGRES_PORT`. Firewall
them to the orchestrator and worker hosts.

## 3. Orchestrator

```bash
cd deploy/orchestrator
cp orchestrator.env.example orchestrator.env   # see the reference below
# DV_SIGNING_KEY, DV_DATA_KEYS and DV_VAULT_KEYS as env lines (notes go to stderr):
docker run --rm -e DV_DEBUG=true --entrypoint python devicevault-orchestrator manage.py generate_keys
docker compose up -d                           # UI on :8080 (DV_HTTP_PORT)
docker compose --profile flower up -d          # ... plus Flower (see Flower below)
```

The `migrate` service runs first: it applies migrations, creates the built-in
**Administrators** user group (global administrators) and, if that user does
not exist, the bootstrap admin from `DV_ADMIN_USERNAME` / `DV_ADMIN_PASSWORD` as
a member of it. Put a TLS-terminating proxy or load balancer in front of `web`,
and set `DV_ALLOWED_HOSTS` and `DV_CSRF_TRUSTED_ORIGINS` to match.

### Users and access

Sign-in uses a server-side session: an HttpOnly cookie (`Secure` unless
`DV_DEBUG`, so serve the UI over HTTPS), stored in the database so every
orchestrator node shares it. Sessions end after `DV_SESSION_IDLE_MIN` without
use and `DV_SESSION_MAX_HOURS` after sign-in. Repeated failed sign-ins lock out a
username or client address for `DV_LOGIN_LOCKOUT_MIN`; the client address is the
last `X-Forwarded-For` hop, which the `web` service adds.

Access comes only from **user groups** (Admin Settings > User Groups): each
grants its members permissions on device groups (View Status, Backup Now, View
Contents, Download, Group Admin), and a group flagged global administrator holds
everything, including application administration. A new user has no access
until a group grants some. Django's `is_staff`/`is_superuser` flags mean
nothing, and there is no `/admin/` site. Admin Settings > Access shows the whole
matrix, and Admin Settings > Audit Log records sign-ins, access changes, backup
content views, diffs and downloads, and refused requests.

With `DV_DB_ENGINE=sqlite` the database lives in the stack's `data` volume, which
limits you to a single orchestrator node (see [High availability](#6-high-availability)).

Every orchestrator node needs the same three keys:

- `DV_SIGNING_KEY` signs every assignment and task sent to workers. Workers pin
  it when first approved, so never change it: a new key means resetting every
  worker.
- `DV_DATA_KEYS` encrypts credentials and location config in the database.
- `DV_VAULT_KEYS` (with `DV_PAYLOAD_ENCRYPTION=true`): collectors encrypt every
  backup to the current vault public key, and device credentials and location
  config are sealed to each worker that may handle them. RabbitMQ, Redis and
  storage workers only see ciphertext; only the orchestrator can decrypt.

Both key rings are `kid=<base64>,...` with the current key first. To rotate,
put a new key (`generate_keys --only data` or `--only vault`) first and keep
the old one after it while anything encrypted with it remains. Keep these keys
backed up: without the vault key, encrypted backups cannot be read.

With `DV_PAYLOAD_ENCRYPTION=false` (the development default) payloads travel in
plaintext; `migrate` warns about this when `DV_DEBUG` is off.

## 4. Workers

One Compose project per worker:

```bash
cd deploy/worker
cp worker.env.example worker.env
docker compose -p dv-collector-dmz up -d
```

A worker needs only `DV_BROKER_URL` and `DV_REDIS_URL`. On first start it
creates its identity in the `state` volume, logs its fingerprint, and registers:

```bash
docker compose -p dv-collector-dmz logs worker | grep worker_identity
```

Then, in the UI under **Admin Settings > Workers**, check that the fingerprint
matches and **Approve** the worker with a role:

- **Collector**: choose the collection groups whose devices it backs up.
- **Storage**: optionally choose the storage targets it serves. Targets can also be
  assigned later under **Admin Settings > Storage Targets**.

The worker starts consuming within seconds. It pins the orchestrator key shown
on the Workers page; check that the fingerprint in its `orchestrator_pinned`
log line matches. To automate approval: `manage.py approve_worker <name>
--role collector --groups <queue id> ...` or `--role storage --targets <name> ...`.

- Keep the `state` volume. Deleting it (or `identity.json`) resets the worker:
  it registers as a new, pending worker.
- **Revoke** stops a worker consuming. **Forget** removes it; if it is still
  running it registers again as pending.

### Storage targets

Under **Admin Settings > Storage Targets**, create a target per place backups go:
a storage driver offered by an approved storage worker, its settings (a form built
from the driver's schema), and the workers that serve it. Each target has its own
queue, `storage.target.<id>`. **Test** asks one of its workers to check the settings.

- **Filesystem** and **Git repository** write to the worker's `storage` volume
  (`/srv/devicevault`); their `path` is relative to it. Only one worker can serve
  such a target.
- **S3 bucket** works with AWS S3 and S3-compatible stores (`endpoint_url`, path-style
  addressing). Several workers can serve one bucket, so a stopped worker doesn't stop
  backups. Leave the access key empty to use the worker's IAM role.
- **PostgreSQL database** stores one `bytea` row per backup in a database of its own,
  independent of DeviceVault's database; define as many as you need. Several workers can
  serve one target. Settings: host, port, database, user, password, schema (default
  `public`), TLS (`off`, `preferred`, `forced`), certificate validation (`none`, `ca`,
  `full`, which needs TLS forced) and an optional PEM CA certificate (empty means the
  worker's system trust store, which only works with `full`). The driver creates the
  table in that schema unless **Create table** is off, in which case a DBA creates it
  first and the user needs only `SELECT, INSERT, UPDATE, DELETE`:

  ```sql
  CREATE TABLE <schema>.devicevault_backups (
      ref text PRIMARY KEY,         -- <device_key>/<timestamp>-<job_id><ext>
      content bytea NOT NULL,
      stored_at timestamptz NOT NULL DEFAULT now()
  );
  ```

  Workers connect with `application_name` `devicevault-worker <worker id>`.
- Secret settings (the S3 secret key, database passwords) are never shown again; leave them empty to keep
  them.
- A target that holds backups cannot be deleted, and its driver cannot change. Changing
  where it writes (path, bucket, prefix, database) makes earlier backups unreadable unless their
  data moves too.

## 5. Flower

Flower shows live workers, queues and tasks. Register each Flower under
**Admin Settings > Flower**, which opens it in a new tab:

- **Proxied** (recommended): the `web` service serves it at `/flower/<slug>/` to
  signed-in administrators only, so Flower needs no login of its own and its port
  stays private. The URL is where `web` reaches Flower, with no path
  (`http://flower:5555`). Flower must run with `--url_prefix=flower/<slug>`
  (`DV_FLOWER_URL_PREFIX`).
- **Direct**: the UI links to the URL as it is. That Flower must secure itself
  (its `--basic-auth` or `--auth` options): anyone who reaches it can stop workers.

The orchestrator stack's optional `flower` service is ready to be proxied:

```bash
docker compose --profile flower up -d
```

Then add an endpoint with slug `local`, URL `http://flower:5555`, proxied. The
service runs with `DV_FLOWER_URL_PREFIX=flower/local` (set it in the shell or the
stack's `.env` to change it) and publishes its own port on `127.0.0.1:5555` only.
With two orchestrator nodes, run it on both: each node's `web` proxies
`http://flower:5555` to its own Flower, and both show the same cluster.

Opening the Flower page gives the browser a session cookie for each proxied
endpoint, scoped to its path and valid for 8 hours or until you sign out. When it
lapses, the proxy sends you back to the page to open Flower again.

A proxied Flower is served from the UI's origin, so treat it as trusted code and
proxy only Flower instances you run. The development stack has no nginx, so its
Flower is a direct endpoint, `http://localhost:5555`; `make dev-seed` adds it.

## 6. High availability

Run two orchestrator nodes behind a load balancer or a virtual IP.

- **PostgreSQL is required**, and every node must use the same database. A SQLite
  orchestrator is a single node: `migrate` records in Redis which database uses
  the message bus (`dv:orchestrator:installation`) and refuses to start a node
  whose database is a different one, such as a second node with its own SQLite
  file. Restoring the same database keeps its identity. If a new database
  deliberately replaces the old one, take the bus over with
  `docker compose run --rm migrate manage claim_installation --force`.
- **Every node has the same configuration**: the same `orchestrator.env`, in
  particular `DV_SECRET_KEY`, `DV_SIGNING_KEY`, `DV_DATA_KEYS` and `DV_VAULT_KEYS`.
- **Every service runs on both nodes.** `web`, `api` and `events` are
  active/active. `scheduler` runs on both, but only the holder of the Redis lease
  `dv:scheduler:leader` schedules backups. The leader renews the lease every tick
  (`DV_SCHEDULER_INTERVAL_SEC`) for 60 seconds, or twice the interval if that is
  longer. Stopping the leader releases the lease and the other node takes over at
  its next tick; if the leader dies, the other node takes over once the lease
  expires. A scheduler logs `This node is now the scheduler leader` when it takes
  over.
- **Front end**: point a load balancer at both nodes' `web` port, with
  `/api/health/` as the health check, or float a virtual IP between them with
  keepalived, for example (`/etc/keepalived/keepalived.conf` on both nodes):

  ```
  vrrp_script devicevault_web {
      script "/usr/bin/curl -fsS -o /dev/null http://127.0.0.1:8080/api/health/"
      interval 5
      fall 2
      rise 2
  }

  vrrp_instance devicevault {
      state BACKUP              # on both nodes; the higher priority holds the address
      interface eth0
      virtual_router_id 51
      priority 100              # 90 on the second node
      advert_int 1
      authentication {
          auth_type PASS
          auth_pass change-me
      }
      virtual_ipaddress {
          192.0.2.10/24
      }
      track_script {
          devicevault_web
      }
  }
  ```

  Terminate TLS on the load balancer or on a proxy on each node, and set
  `DV_ALLOWED_HOSTS` and `DV_CSRF_TRUSTED_ORIGINS` to the shared name.

The infrastructure's own redundancy is outside these stacks:

- **PostgreSQL**: a primary and a streaming replica with a failover manager
  (Patroni, repmgr...). List every host in `DV_DB_HOST`, comma separated
  (`pg1,pg2`); the orchestrator connects to whichever one accepts writes.
- **RabbitMQ**: a three-node cluster. List every node in `DV_BROKER_URL`,
  separated by `;` (`amqp://user:pass@mq1:5672//;amqp://user:pass@mq2:5672//`);
  orchestrators and workers fail over between them.
- **Redis**: one URL for now (Redis Sentinel isn't supported yet). Run a replica
  managed by Sentinel and give clients an address that follows the primary, such
  as a keepalived address moved by Sentinel's `client-reconfig-script`. Redis
  holds only transient state: backups in transit, the scheduler lease, the
  database claim and Celery results. Losing it fails the jobs in flight, and the
  next `migrate` claims the bus again.

## Configuration reference

Every variable can be supplied as a file by setting `<NAME>_FILE` (Docker
secrets). The file takes precedence.

### Orchestrator

| Variable | Default | Purpose |
|---|---|---|
| `DV_SECRET_KEY` | required unless `DV_DEBUG` | Django secret key |
| `DV_DEBUG` | `false` | Development mode; never in production |
| `DV_ALLOWED_HOSTS` | none (`*` in debug) | Hostnames the UI is served on |
| `DV_CSRF_TRUSTED_ORIGINS` | none | Full origins (`https://host`) behind HTTPS |
| `DV_TIMEZONE` | `UTC` | Display timezone (storage is always UTC) |
| `DV_LOG_LEVEL` | `INFO` | |
| `DV_DB_ENGINE` | `sqlite` | `sqlite` or `postgres` |
| `DV_DB_NAME` | `/var/lib/devicevault/devicevault.sqlite3` or `devicevault` | |
| `DV_DB_HOST` / `DV_DB_PORT` / `DV_DB_USER` / `DV_DB_PASSWORD` | `localhost` / `5432` / `devicevault` / empty | PostgreSQL only; several hosts comma separated |
| `DV_BROKER_URL` | `amqp://guest:guest@localhost:5672//` | RabbitMQ; several nodes separated by `;` |
| `DV_REDIS_URL` | `redis://localhost:6379/0` | Redis |
| `DV_RESULT_BACKEND` | `DV_REDIS_URL` | Celery result backend |
| `DV_BROKER_API` | none | RabbitMQ management API, for Flower |
| `DV_FLOWER_URL_PREFIX` | none (`flower/local` in the orchestrator stack) | `flower` service: its path, `flower/<slug>` when proxied |
| `DV_ADMIN_USERNAME` / `DV_ADMIN_PASSWORD` / `DV_ADMIN_EMAIL` | `admin` / required on first run / empty | Bootstrap admin |
| `DV_LOCAL_AUTH_ENABLED` | `true` | Allow creating local user accounts |
| `DV_SESSION_IDLE_MIN` | `60` | A session unused this long ends |
| `DV_SESSION_MAX_HOURS` | `12` | A session ends this long after sign-in, used or not |
| `DV_LOGIN_MAX_FAILURES` / `DV_LOGIN_LOCKOUT_MIN` | `5` / `15` | Failed sign-ins (per username, and per client address) within the window that lock it out for the window |
| `DV_API_WORKERS` / `DV_API_TIMEOUT` | `3` / `90` | gunicorn workers and request timeout (seconds) |
| `DV_SIGNING_KEY` | required | Ed25519 key signing everything sent to workers (`generate_keys`) |
| `DV_DATA_KEYS` | required | AES-256 key ring for secrets at rest (`generate_keys`) |
| `DV_PAYLOAD_ENCRYPTION` | `false` | Encrypt backups and secrets in transit; turn on for deployments |
| `DV_VAULT_KEYS` | required with payload encryption | X25519 key ring backups are encrypted to (`generate_keys`) |
| `DV_WORKER_ONLINE_TIMEOUT_SEC` | `90` | A worker is offline after this long without a heartbeat |
| `DV_EVENTS_CONCURRENCY` | `4` | Processes in the `events` service (worker and job events) |
| `DV_COLLECT_TIMEOUT_SEC` | `120` | Time a collector driver gets to reach and read a device, per attempt |
| `DV_JOB_TIMEOUT_MIN` | `120` | A backup job still unfinished after this long is marked timed out |
| `DV_SCHEDULER_INTERVAL_SEC` | `30` | How often the scheduler checks for due schedules (and renews its lease) |

### Worker

| Variable | Default | Purpose |
|---|---|---|
| `DV_BROKER_URL` | `amqp://guest:guest@localhost:5672//` | RabbitMQ |
| `DV_REDIS_URL` | `redis://localhost:6379/0` | Redis |
| `DV_WORKER_NAME` | `worker` | Display name (`<name>@<container>`) |
| `DV_WORKER_CONCURRENCY` | `2` | Parallel tasks |
| `DV_LOG_LEVEL` | `INFO` | |
| `DV_STATE_DIR` | `/var/lib/devicevault` | Where the worker keeps its identity |
| `DV_WORKER_HEARTBEAT_INTERVAL_SEC` | `30` | Heartbeat interval |

## Known limitations (pre-release)

- TLS to RabbitMQ and Redis works through `amqps://` and `rediss://` URLs, but
  the infra stack doesn't configure TLS itself yet.
- Backups are staged whole in Redis between collection and storage (24 hours at
  most), so size Redis memory for your largest backups times concurrent jobs.
- Retention policies are stored but not yet applied.
- Redis is a single endpoint; Redis Sentinel URLs are not supported yet.
