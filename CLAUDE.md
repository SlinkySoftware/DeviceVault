# DeviceVault — agent guide

Read [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md) first. It is the agreed target design and
phased delivery plan; new work should move the code toward it, not entrench the current shape.

## Ground rules

- **Docker only.** No host Python/Node. Run every tool through `make` (see `Makefile`):
  `make lint`, `make fmt`, `make test`, `make frontend-build`, `make lock`, `make dev-up`.
  For ad-hoc commands, use the dev image:
  `docker run --rm -v "$PWD":/workspace -u "$(id -u):$(id -g)" -e HOME=/tmp -w /workspace/orchestrator devicevault-dev <cmd>`.
- **Dependencies**: edit `orchestrator/pyproject.toml`, then `make lock`. `uv.lock` is committed.
  Frontend deps are pinned in `frontend/package.json` with `package-lock.json` committed.
- **No backward compatibility required.** Nothing is deployed. Change models freely, but
  keep migrations generated (`makemigrations`), and the test suite guards against drift.
- **No CI service yet.** `make check` is what a pipeline will run; keep it green.
- One phase per branch and PR, as listed in the architecture doc.

## Layout

- `orchestrator/`: Django project (`devicevault/` settings and urls) plus apps: `api`,
  `audit`, `backups`, `core`, `credentials`, `devices`, `locations`, `policies`, `crypto`.
  It still contains the worker code (`celery_app.py`, `devicevault_worker.py`, `storage/`,
  `backups/plugins/`); phase 2 moves that to `worker/` without Django.
- `frontend/`: Quasar/Vue SPA. API client in `src/services/api.js`.
- `dev-env/` + `devicevault-docker-dev.sh`: current dev stack (replaced by `deploy/` in phase 2).

## Conventions

- Python 3.14, ruff-formatted (single quotes, 120 columns). Tests use pytest with
  pytest-django, live next to the code in `<app>/tests/`, and use the `db` fixture.
- API changes: update `api/serializers.py` and `api/views.py` together, and keep
  `frontend/src/services/api.js` in step.
- Workers must not import Django. The orchestrator owns all database access; workers
  communicate only through RabbitMQ and Redis.
- Collector plugins expose `PLUGIN = BackupPlugin(...)` in `backups/plugins/<name>.py`.
  Storage backends are registered in `storage/tasks.py`. Both become entry-point
  driver registries in later phases.
