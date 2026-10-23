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
- Device-group RBAC (per-group roles for users and auth groups)
- On-demand ("backup now") collection through Celery collectors, routed by collection group
- Backup methods as plugins (`noop`, `binary_dummy`, `mikrotik_ssh`)
- Storage to local filesystem or git through Celery storage workers
- Optional envelope encryption of stored backups (AES-256-GCM)
- Backup viewing, download and side-by-side comparison
- Dashboard statistics and audit log
- Worker registration and liveness view
- Local authentication

Not yet implemented (see the plan): scheduled backups, retention enforcement, S3 and
database storage, push collection, external authentication (LDAP/SAML/Entra ID).

## Technology

| Layer | Stack |
|---|---|
| Orchestrator | Python 3.14, Django 6.1, Django REST Framework |
| Workers | Celery 5.6 on RabbitMQ, Redis for locks and results |
| Frontend | Vue 3.5, Quasar 2, Node 24 |
| Database | SQLite (single node) or PostgreSQL |
| Tooling | uv, ruff, pytest, Docker |

## Development

Requirements: Docker (with Compose) and `make`. Everything else runs in containers.

```bash
make dev-up        # start the full dev stack (db, redis, rabbitmq, orchestrator, workers, flower, frontend)
make dev-status    # show container status
make dev-logs      # tail logs
make dev-down      # stop the stack
make dev-reset     # stop and delete all dev data
```

| Service | URL |
|---|---|
| Web UI | http://localhost:9000 (admin / admin) |
| API | http://localhost:8000/api/ |
| Flower | http://localhost:5555 |
| RabbitMQ management | http://localhost:15672 (guest / guest) |

Load demo data into a running stack:

```bash
docker exec devicevault-docker-dev-orchestrator python manage.py seed_demo
```

### Quality checks

```bash
make lint            # ruff lint + format check
make fmt             # apply ruff fixes and formatting
make test            # pytest
make frontend-build  # production build of the SPA
make check           # all of the above
make lock            # refresh uv.lock after editing a pyproject.toml
```

## Repository layout

```
orchestrator/   Django project, Celery app and (until phase 2) the worker code
frontend/       Quasar/Vue single-page app
dev-env/        Docker development stack (replaced by deploy/ in phase 2)
docs/           Architecture and delivery plan
Makefile        Single entry point for development and CI
```

## License

GNU General Public License v3.0 or later. See [LICENSE.md](LICENSE.md).
