# Deploying DeviceVault

DeviceVault ships as three images and three independent Compose stacks. The
stacks never talk to each other directly: orchestrators and workers connect
out to RabbitMQ and Redis in the infra stack, and that is all.

| Stack | Path | Runs |
|---|---|---|
| Infra | `deploy/infra` | RabbitMQ, Redis, PostgreSQL (optional) |
| Orchestrator | `deploy/orchestrator` | web (nginx + UI), api, result consumers, worker monitor, Flower (optional) |
| Worker | `deploy/worker` | one collector or storage worker per Compose project |

> **Status:** pre-release. Workers still need their queues (and storage workers
> their encryption keys) configured locally. Both go away in phases 4 and 5,
> when the orchestrator assigns work. See [ARCHITECTURE.md](ARCHITECTURE.md).

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
docker compose up -d                           # UI on :8080 (DV_HTTP_PORT)
docker compose --profile flower up -d          # ... plus Flower on :5555
```

The `migrate` service runs first: it applies migrations and creates the
bootstrap admin from `DV_ADMIN_USERNAME` / `DV_ADMIN_PASSWORD` if that user does
not exist. Put a TLS-terminating proxy or load balancer in front of `web`, and
set `DV_ALLOWED_HOSTS` and `DV_CSRF_TRUSTED_ORIGINS` to match.

With `DV_DB_ENGINE=sqlite` the database lives in the stack's `data` volume, which
limits you to a single orchestrator node.

## 4. Workers

One Compose project per worker:

```bash
cd deploy/worker
cp worker.env.example worker.env
docker compose -p dv-collector-dmz up -d
```

A worker needs only `DV_BROKER_URL` and `DV_REDIS_URL`, plus these interim
settings:

- `DV_WORKER_QUEUES`: collectors use `collector.group.<queue id>` (the
  collection group's RabbitMQ queue ID in the UI). Storage workers use
  `storage.fs,storage.git`.
- `DV_ENCRYPTION_KEYS` / `DV_ENCRYPTION_DEFAULT_KID`: storage workers only, when
  per-device encryption is used.

Filesystem and git backup locations must point under `/srv/devicevault`, which
is the worker's `storage` volume.

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
| `DV_DB_HOST` / `DV_DB_PORT` / `DV_DB_USER` / `DV_DB_PASSWORD` | `localhost` / `5432` / `devicevault` / empty | PostgreSQL only |
| `DV_BROKER_URL` | `amqp://guest:guest@localhost:5672//` | RabbitMQ |
| `DV_REDIS_URL` | `redis://localhost:6379/0` | Redis |
| `DV_RESULT_BACKEND` | `DV_REDIS_URL` | Celery result backend |
| `DV_BROKER_API` | none | RabbitMQ management API, for Flower |
| `DV_ADMIN_USERNAME` / `DV_ADMIN_PASSWORD` / `DV_ADMIN_EMAIL` | `admin` / required on first run / empty | Bootstrap admin |
| `DV_LOCAL_AUTH_ENABLED` | `true` | Allow local user accounts |
| `DV_API_WORKERS` / `DV_API_TIMEOUT` | `3` / `90` | gunicorn workers and request timeout (seconds) |
| `DV_WORKER_ONLINE_TIMEOUT_SEC` / `DV_WORKER_PONG_GRACE_SEC` / `DV_WORKER_PING_INTERVAL_SEC` | `90` / `45` / `30` | Worker liveness |
| `DV_ENCRYPTION_ENABLED` / `DV_ENCRYPTION_KEYS` / `DV_ENCRYPTION_DEFAULT_KID` | `false` / none / none | Interim stored-backup encryption |

### Worker

| Variable | Default | Purpose |
|---|---|---|
| `DV_BROKER_URL` | `amqp://guest:guest@localhost:5672//` | RabbitMQ |
| `DV_REDIS_URL` | `redis://localhost:6379/0` | Redis |
| `DV_WORKER_NAME` | `worker` | Display name (`<name>@<container>`) |
| `DV_WORKER_CONCURRENCY` | `2` | Parallel tasks |
| `DV_LOG_LEVEL` | `INFO` | |
| `DV_WORKER_QUEUES` | required (interim) | Queues to consume |
| `DV_ENCRYPTION_*` | none (interim) | Storage workers only |

## Known limitations (pre-release)

- Backups travel inside RabbitMQ messages, and RabbitMQ 4 rejects messages over
  16 MiB by default. Phase 5 moves payloads to Redis.
- TLS to RabbitMQ and Redis works through `amqps://` and `rediss://` URLs, but
  the infra stack doesn't configure TLS itself yet.
- Scheduled backups don't run yet (phase 5). Use "Backup now".
