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
  task/queue/stream names, the Celery app factory, presence constants, `crypto`.
  Shared by both sides; must not import Django.
- `worker/` (`devicevault_worker`): Celery app (`devicevault_worker.app`), collect and
  storage tasks, `plugins/` (collector plugins), `storage/` (backends), `presence`.
  Must not import Django (a test enforces it).
- `orchestrator/`: Django project (`devicevault/` settings, urls, `celery.py` for
  sending tasks) plus apps: `api`, `audit`, `backups`, `core`, `credentials`, `devices`,
  `locations`, `policies`. Settings are env-only; tests use `devicevault.test_settings`.
  It depends on `worker` only for the plugin catalogue (temporary, until phase 4).
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
- Collector plugins expose `PLUGIN = BackupPlugin(...)` in
  `worker/src/devicevault_worker/plugins/<name>.py`. Storage backends are registered in
  `worker/src/devicevault_worker/storage/tasks.py`. Both become entry-point driver
  registries in later phases.
- Configuration is `DV_*` environment variables read through `devicevault_protocol.env`;
  never add config files. Document new variables in `docs/DEPLOYMENT.md` and the
  relevant `*.env.example`.
