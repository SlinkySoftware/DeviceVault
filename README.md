# DeviceVault

DeviceVault collects and versions configuration backups from network devices. A central
orchestrator schedules work, collectors connect to devices (for example over SSH to run
`show running-config`), and storage workers persist the results. Components talk to each
other only through RabbitMQ and Redis.

> **Status:** pre-release and under active restructuring. The target design and the
> phased delivery plan are in [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md). This README
> describes what works today.

## What works today

- Device inventory with device types, manufacturers, device groups and collection groups
- Device-group RBAC (per-group roles for users and auth groups), enforced by the API;
  configuration and user management are administrator-only
- Backup jobs, on demand ("backup now") or on schedules (daily, weekly, monthly, cron) in the
  display timezone, tracked from request to storage with retries, timeouts and per-job logs
- Collector drivers: `cisco_ios` and `mikrotik_ssh_export` (SSH via Netmiko), plus `demo_config`,
  `noop` and `binary_dummy` for testing. Per-device driver settings come from each driver's
  schema (form in the UI, validated by the API); more drivers can be installed as
  `devicevault.collectors` entry points
- Storage targets, each served by chosen storage workers: local filesystem, git (one commit
  per backup), S3 and S3-compatible buckets, or PostgreSQL databases (both shared by several
  workers); settings from the
  driver's schema, with a Test button. More drivers can be installed as `devicevault.storage`
  entry points
- Payload encryption (`DV_PAYLOAD_ENCRYPTION`): collectors encrypt backups to the
  orchestrator's vault key, and credentials are sealed to each collector, so RabbitMQ, Redis
  and storage workers only see ciphertext; credentials are also encrypted in the database
- Backup viewing, download and side-by-side comparison
- Dashboard statistics and audit log
- Zero-configuration workers: they register themselves, an admin approves them with a
  role and assignment, and everything sent to them is signed by the orchestrator
- Local authentication

Not yet implemented (see the plan): scheduled backups, retention enforcement, push collection, external authentication (LDAP/SAML/Entra ID).

## Technology

| Layer | Stack |
|---|---|
| Orchestrator | Python 3.14, Django 6.1, Django REST Framework |
| Workers | Celery 5.6 on RabbitMQ, Redis for locks and results |
| Frontend | Vue 3.5, Quasar 2, TypeScript, Pinia, Vitest, Node 24 |
| Database | SQLite (single node) or PostgreSQL |
| Tooling | uv, ruff, pytest, Docker |

## Development

Requirements: Docker (with Compose) and `make`. Everything else runs in containers.

```bash
make dev-up        # start the dev stack: infra, orchestrator, 2 collectors, 1 storage worker, flower, frontend
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
make test            # pytest for protocol, worker and orchestrator
make frontend-lint   # ESLint + vue-tsc type check
make frontend-test   # Vitest unit tests
make frontend-build  # production build of the SPA
make check           # all of the above
make lock            # refresh uv.lock after editing a pyproject.toml
make images          # build the orchestrator, worker and web images
```

## Deployment

Three independent stacks (infra, orchestrator, workers). See
[docs/DEPLOYMENT.md](docs/DEPLOYMENT.md).

## Repository layout

```
protocol/       Shared contracts: env config, queue/task names, Celery factory, crypto (no Django)
worker/         Collection and storage worker: Celery tasks, collector and storage drivers (no Django)
orchestrator/   Django project: API, worker events, result consumers
frontend/       Quasar/Vue single-page app (TypeScript)
docker/         Image definitions and entrypoints
deploy/         Compose stacks: infra, orchestrator, worker, dev
docs/           Architecture, delivery plan and deployment guide
Makefile        Single entry point for development and CI
```

## License

GNU General Public License v3.0 or later. See [LICENSE.md](LICENSE.md).
