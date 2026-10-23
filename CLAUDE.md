# DeviceVault — agent guide

Read [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md) first. It is the agreed target design and
phased delivery plan; new work should move the code toward it, not entrench the current shape.

## Ground rules

- **Docker only.** No host Python/Node. Run every tool through `make` (see `Makefile`):
  `make lint`, `make fmt`, `make test`, `make frontend-lint`, `make frontend-test`,
  `make frontend-build`, `make lock`, `make dev-up`.
  For ad-hoc commands, use the dev image (`make dev-image` builds it):
  `docker run --rm -v "$PWD":/workspace -u "$(id -u):$(id -g)" -e HOME=/tmp -w /workspace/orchestrator devicevault-dev <cmd>`.
- **Dependencies**: edit the package's `pyproject.toml` (`protocol/`, `worker/` or `orchestrator/`), then `make lock`. `uv.lock` is committed.
  Frontend deps are pinned in `frontend/package.json` with `package-lock.json` committed.
- **No backward compatibility required.** Nothing is deployed. Change models freely, but
  keep migrations generated (`makemigrations`), and the test suite guards against drift.
- **No CI service yet.** `make check` is what a pipeline will run; keep it green.
- One phase per branch and PR, as listed in the architecture doc.

## Layout

- `protocol/` (`devicevault_protocol`): env helpers (`DV_*`, `<NAME>_FILE` secrets),
  task and queue names, the job protocol (`jobs`), the Celery app factory, presence constants, `crypto`.
  Shared by both sides; must not import Django.
- `worker/` (`devicevault_worker`): Celery app (`devicevault_worker.app`), collect and
  storage tasks, `drivers/` (collector drivers), `storage/` (backends), `identity`
  (persistent worker id and keys), `agent` (registration and assignments), `trust`
  (task signature checks). Must not import Django (a test enforces it).
- `orchestrator/`: Django project (`devicevault/` settings, urls, `celery.py` for
  sending tasks) plus apps: `api`, `audit`, `backups`, `core`, `credentials`, `devices`,
  `locations`, `policies`. Settings are env-only; tests use `devicevault.test_settings`.
  `core/workers.py` is the worker registry (events, approval, assignments, driver
  catalogue); `core/signing.py` holds the orchestrator signing key. The orchestrator
  must not import the worker package.
- `frontend/`: Quasar 2 / Vue 3 SPA in TypeScript. Talks to same-origin `/api` (nginx in
  production, the Quasar dev proxy in development). `src/api/` (axios client,
  `types.ts` DTOs, `endpoints.ts` typed calls), `src/stores/` (Pinia: auth, theme,
  settings), `src/router/` (routes + guard), `src/composables/` (`useCrud`,
  `useNotify`, `usePolling`), `src/components/`, `src/pages/` (admin pages under
  `pages/admin/`), `src/utils/` (datetime, diff, rules...). Original artwork lives in
  `frontend/branding/`; `public/` holds only web-sized assets.
- `docker/`: `Dockerfile` (targets `orchestrator`, `worker`, `dev`), `web.Dockerfile`,
  entrypoints (`dv-orchestrator <role>`, `dv-worker`).
- `deploy/`: Compose stacks `infra`, `orchestrator`, `worker`, and `dev` (everything on
  one host, source bind-mounted).

## Conventions

- Python 3.14, ruff-formatted (single quotes, 120 columns). Tests use pytest with
  pytest-django, live next to the code in `<app>/tests/`, and use the `db` fixture.
- API changes: update `api/serializers.py` and `api/views.py` together, and keep
  `frontend/src/api/types.ts` and `endpoints.ts` in step.
- API permissions: every view states its `permission_classes` (`IsAdmin`,
  `IsAdminOrReadOnly` in `api/permissions.py`, or device-group checks); never rely on
  the UI hiding something. Secrets in serializers use `AdminOnlyFieldsMixin`.
- Frontend: `<script setup lang="ts">` only (ESLint enforces it); strict TypeScript
  (`make frontend-lint` runs ESLint and vue-tsc). Import via the `@/` alias. Admin CRUD
  pages use `useCrud` + `FormDialog` + `PageCard`; show API errors with
  `useNotify().error(err, fallback)`. Never render untrusted text with `v-html`.
  Tests are Vitest specs next to the code (`*.spec.ts`).
- Workers must not import Django. The orchestrator owns all database access; workers
  communicate only through RabbitMQ and Redis.
- Everything the orchestrator sends a worker is signed: wrap task parameters with
  `core.signing.sign_task(...)` and have the worker task call `verified_payload(...)`
  first. Never add an unsigned task or a worker-side config setting; workers get
  configuration only through their assignment.
- Backup methods shown or accepted by the API come from `core.workers.driver_catalogue()`
  (what approved collectors advertise), not from worker code.
- Collector drivers subclass `CollectorDriver` (`worker/src/devicevault_worker/drivers/base.py`)
  with a pydantic `Params` model, and raise `TransientError` (retried) or `PermanentError`.
  Built-ins are listed in `drivers/__init__.py`; third-party drivers register under the
  `devicevault.collectors` entry point. Storage backends live in `storage/backends.py`.
- Secrets sent to workers go through `core.keys.add_secret` (sealed per worker when payload
  encryption is on) and come out through `devicevault_worker.payload.secret`. Secret model
  fields use `core.fields.EncryptedJSONField`.
- Backups are `backups.models.BackupJob`s: create them with `backups.jobs.create_job`, and let
  worker events drive their state (`backups.jobs.handle_job_event`). Never trust a worker's
  claim without checking its signature and approval.
- Configuration is `DV_*` environment variables read through `devicevault_protocol.env`;
  never add config files. Document new variables in `docs/DEPLOYMENT.md` and the
  relevant `*.env.example`.
