# DeviceVault

DeviceVault collects, versions and protects configuration backups from network devices. It
polls devices on a schedule (or on demand) and accepts files that devices push to it, stores
every backup on the storage targets you choose, and lets you view, download and compare
them. Access is controlled per device group, with local, LDAP and OIDC sign-in, and every
security-relevant action is audited.

The platform is split into independently deployed parts that talk to each other only through
RabbitMQ and Redis: an **orchestrator** (API, web UI, scheduler), **workers** (collectors
and storage workers) and optional **receivers** (the only component that accepts connections
from devices). The design and its decisions are in [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md);
ideas for what comes next are in [docs/ROADMAP.md](docs/ROADMAP.md).

## Features

### Collecting backups

- **Polling** over SSH: on demand ("backup now") or on schedules (daily, weekly, monthly or
  cron) in the display timezone. Jobs are tracked from request to storage with retries,
  timeouts and per-job logs.
- **Push collection**: devices upload their configuration unprompted over **SCP, SFTP or
  TFTP** to a receiver (for example Cisco `archive` on `write memory`). Devices are matched by
  source address, with an optional filename pattern; uploads up to 512 MiB; rejected
  uploads are refused at the protocol level, audited and listed per receiver. TFTP is an
  explicit per-device opt-in because it is unauthenticated.
- **Collector drivers**: `cisco_ios` and `mikrotik_ssh_export` (SSH via Netmiko), plus
  `demo_config`, `noop` and `binary_dummy` for testing. Per-device settings come from each
  driver's schema (a form in the UI, validated by the API). Install more drivers as
  `devicevault.collectors` entry points.

### Storing and viewing backups

- **Storage targets**, each served by the workers you assign: local filesystem, git (one
  commit per backup), S3 and S3-compatible buckets, or PostgreSQL. Settings come from the
  driver's schema, with a Test button. Install more drivers as `devicevault.storage` entry
  points.
- Backup viewing, download and side-by-side comparison.
- Dashboard statistics and a searchable audit log.

### Security

- **Authentication**: local accounts, LDAP and OIDC (Entra ID, Okta, Authentik and
  others). Several identity providers can coexist; identities link on an immutable subject,
  and external group membership is synced at login. A break-glass local administrator
  survives a misconfigured provider. Server-side sessions with idle and absolute timeouts.
- **Authorization**: user groups with per-device-group grants (view, backup now, view
  contents, download, admin) and global administrators, enforced by the API; hidden
  objects return 404.
- **Signed control plane**: everything the orchestrator sends a worker or receiver is
  signed, and workers pin the orchestrator's key on first contact.
- **Payload encryption** (`DV_PAYLOAD_ENCRYPTION`): collectors and receivers encrypt backups
  to the orchestrator's vault key and credentials are sealed to each recipient, so RabbitMQ,
  Redis and storage workers only see ciphertext. Credentials and provider secrets are also
  encrypted in the database.
- **Audit log** of sign-ins, grants, approvals, backups, reads and refused pushes.

### Operations

- **Zero-configuration workers and receivers**: they register themselves, an administrator
  approves them (checking their fingerprint) and assigns a role, and they receive all
  configuration from the orchestrator.
- **High availability**: two active orchestrator nodes with a leader-elected scheduler,
  PostgreSQL and a load balancer in front (SQLite is single-node and enforced).
- **Monitoring**: Flower endpoints stored in the UI and proxied behind the same
  authentication.
- Docker is the only deployment target: four images and four independent Compose stacks.

### Known gaps

Retention policies are stored but not yet enforced, and Redis Sentinel is not supported.
Both are scheduled work; see [docs/ROADMAP.md](docs/ROADMAP.md) and the limitations in
[docs/DEPLOYMENT.md](docs/DEPLOYMENT.md).

## Architecture at a glance

```
 infra:         PostgreSQL | SQLite     RabbitMQ     Redis
 orchestrator:  web (nginx + SPA) · api · events · scheduler · flower (optional)
 workers:       collectors (poll devices) · storage workers (write targets)
 receivers:     SCP/SFTP and TFTP listeners (devices push to them)
```

Backup content travels collector (or receiver) → Redis → storage worker, and a job is
stored only when both sides report the same SHA-256.

## Technology

| Layer | Stack |
|---|---|
| Orchestrator | Python 3.14, Django 6.1, Django REST Framework |
| Workers | Celery 5.6 on RabbitMQ, Redis for locks, results and staged blobs |
| Receivers | asyncio, asyncssh (SCP/SFTP), a write-only TFTP server |
| Frontend | Vue 3.5, Quasar 2, TypeScript, Pinia, Vitest, Node 24 |
| Database | SQLite (single node) or PostgreSQL |
| Tooling | uv, ruff, pytest, Docker |

## Deployment

Four independent stacks (infra, orchestrator, workers, receivers) built from four images.
See [docs/DEPLOYMENT.md](docs/DEPLOYMENT.md) for building images, configuration, users and
access, storage targets, push receivers, Flower, high availability and the configuration
reference.

## Development

Requirements: Docker (with Compose) and `make`. Everything else runs in containers.

```bash
make dev-up        # start the dev stack: infra, orchestrator, collectors, storage worker, receiver, flower, frontend
make dev-seed      # load demo data and approve the dev workers
make dev-ps        # container status
make dev-logs      # tail all logs (SERVICE=api for one)
make dev-down      # stop the stack
make dev-reset     # stop and delete all dev data
```

| Service | URL |
|---|---|
| Web UI (hot reload) | http://localhost:9000 (admin / admin) |
| API (Django runserver) | http://localhost:8000/api/ |
| Flower | http://localhost:5555 |
| RabbitMQ management | http://localhost:15672 (devicevault / devicevault) |

Ports can be moved with `DV_DEV_WEB_PORT`, `DV_DEV_API_PORT`, `DV_DEV_FLOWER_PORT`,
`DV_RABBITMQ_PORT`, `DV_RABBITMQ_MANAGEMENT_PORT`, `DV_REDIS_PORT` and `DV_POSTGRES_PORT`.

### Quality checks

```bash
make lint            # ruff lint + format check
make fmt             # apply ruff fixes and formatting
make test            # pytest for protocol, worker, receiver and orchestrator
make frontend-lint   # ESLint + vue-tsc type check
make frontend-test   # Vitest unit tests
make frontend-build  # production build of the SPA
make check           # all of the above
make lock            # refresh uv.lock after editing a pyproject.toml
make images          # build the orchestrator, worker, receiver and web images
```

Contributors and coding agents should read [CLAUDE.md](CLAUDE.md) for the ground rules and
conventions.

## Repository layout

```
protocol/       Shared contracts and runtime: env config, queue/task names, job protocol, Celery factory,
                crypto, worker identity, registration agent, task trust, blob staging (no Django)
worker/         Collector and storage worker: Celery tasks, collector and storage drivers (no Django)
receiver/       Push receiver: SCP/SFTP and TFTP listeners, ingest and events (no Django)
orchestrator/   Django project: API, accounts and auth providers, backups, devices, storage, push,
                monitoring, audit, scheduler and event handling
frontend/       Quasar/Vue single-page app (TypeScript)
docker/         Image definitions and entrypoints
deploy/         Compose stacks: infra, orchestrator, worker, receiver, dev
docs/           Architecture and delivery plan, roadmap, deployment guide
Makefile        Single entry point for development and CI
```

## License

GNU General Public License v3.0 or later. See [LICENSE.md](LICENSE.md).
