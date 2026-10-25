# DeviceVault — agent guide

Read [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md) first. It is the agreed target design and
phased delivery plan; new work should move the code toward it, not entrench the current shape.

## Ground rules

- **Docker only.** No host Python/Node. Run every tool through `make` (see `Makefile`):
  `make lint`, `make fmt`, `make test`, `make test-postgres`, `make frontend-lint`, `make frontend-test`,
  `make frontend-build`, `make lock`, `make dev-up`.
  For ad-hoc commands, use the dev image (`make dev-image` builds it):
  `docker run --rm -v "$PWD":/workspace -u "$(id -u):$(id -g)" -e HOME=/tmp -w /workspace/orchestrator devicevault-dev <cmd>`.
- **Dependencies**: edit the package's `pyproject.toml` (`protocol/`, `worker/`, `receiver/` or `orchestrator/`), then `make lock`. `uv.lock` is committed.
  Frontend deps are pinned in `frontend/package.json` with `package-lock.json` committed.
- **No backward compatibility required.** Nothing is deployed. Change models freely, but
  keep migrations generated (`makemigrations`), and the test suite guards against drift.
- **CI is GitHub Actions** (`.github/workflows/`): `ci.yml` runs `make check` on every PR (required to merge),
  `release.yml` publishes images to GHCR when a `vX.Y.Z` tag is pushed. Workflows only call `make` targets; keep it green.
- **Version**: the root `VERSION` file is the source. Bump it with `make set-version V=X.Y.Z` (updates every
  `pyproject.toml`, `package.json`, the lockfiles), never by hand. Code reads it with `devicevault_protocol.version.version()`.
- **Contributing**: work on a branch, open a PR to `master`, Conventional Commit messages (see `CONTRIBUTING.md`).
- One phase per branch and PR, as listed in the architecture doc.

## Layout

- `protocol/` (`devicevault_protocol`): env helpers (`DV_*`, `<NAME>_FILE` secrets),
  task and queue names, the job protocol (`jobs`), the Celery app factory, presence constants, `crypto`,
  and the runtime workers and receivers share: `identity` (persistent worker id and keys), `agent`
  (registration and assignments; subclasses `apply` them), `trust` (task signature checks), `blobs`
  (chunked, streamed Redis staging) and `logs`. Shared by all sides; must not import Django.
- `worker/` (`devicevault_worker`): Celery app (`devicevault_worker.app`), collect and
  storage tasks, `drivers/` (collector drivers), `storage/` (storage drivers and tasks), `agent`
  (applies assignments as Celery queue consumers). Must not import Django (a test enforces it).
- `receiver/` (`devicevault_receiver`): the push receiver, its own image. Not a Celery worker: an
  asyncio loop (`main`) running the listeners (`ssh`: asyncssh SCP/SFTP; `tftp`: write requests; both
  upload-only), `agent`
  (applies the assignment's `receiver` section, `config`), `ingest` (spool, encrypt, stage, report)
  and `events` (signed `push.*` events, rate-limited refusals). Must not import Django.
- `orchestrator/`: Django project (`devicevault/` settings, urls, `celery.py` for
  sending tasks) plus apps: `accounts` (user groups, memberships, device-group grants;
  `access.py` decides every authorization; `sessions.py` timeouts; `login.py` password sign-in,
  identity linking and group sync; `providers/` identity provider kinds (pydantic `Config`; LDAP, OIDC); `oidc_views.py` the OIDC redirects;
  `api.py` sign-in, users and user groups; `provider_api.py` auth providers), `api`, `audit` (`log.record(...)`), `backups` (jobs, scheduler, `retention.py` the retention pass, `changes.py` change summaries), `core`, `credentials`, `devices`,
  `monitoring` (Flower endpoints and the `/api/flower-auth/` check nginx makes before proxying them),
  `policies`, `search` (config search: `tokens.py` secret tokens, `indexing.py` documents and the catch-up pass,
  `query.py` searches), `push` (receiver settings and refusals; `service.py` builds receiver assignments and
  re-sends them when push-enabled devices change, `events.py` turns pushed files into jobs), `storage`
  (storage targets; `storage/service.py` sends their tasks). Settings
  are env-only; tests use `devicevault.test_settings`. `core/workers.py` is the worker
  registry (events, approval, assignments, collector and storage driver catalogues);
  `core/signing.py` holds the signing key, `core/keys.py` the data and vault keys, and `core/installation.py`
  the one-database-per-bus claim `migrate` makes. The orchestrator
  must not import the worker or receiver packages.
- `frontend/`: Quasar 2 / Vue 3 SPA in TypeScript. Talks to same-origin `/api` (nginx in
  production, the Quasar dev proxy in development). `src/api/` (axios client,
  `types.ts` DTOs, `endpoints.ts` typed calls), `src/stores/` (Pinia: auth with `can(flag, group)`,
  theme, settings), `src/router/` (routes + guard), `src/composables/` (`useCrud`,
  `useNotify`, `usePolling`), `src/components/`, `src/pages/` (admin pages under
  `pages/admin/`), `src/utils/` (datetime, diff, grants, rules...). Original artwork lives in
  `frontend/branding/`; `public/` holds only web-sized assets.
- `docker/`: `Dockerfile` (targets `orchestrator`, `worker`, `receiver`, `dev`), `web.Dockerfile`,
  entrypoints (`dv-orchestrator <role>`, `dv-worker`, `dv-receiver`).
- `deploy/`: Compose stacks `infra`, `orchestrator`, `worker`, `receiver` (host networking), and `dev`
  (everything on one host, source bind-mounted).

## Conventions

- Python 3.14, ruff-formatted (single quotes, 120 columns). Tests use pytest with
  pytest-django, live next to the code in `<app>/tests/`, and use the `db` fixture.
- API changes: update `api/serializers.py` and `api/views.py` together, and keep
  `frontend/src/api/types.ts` and `endpoints.ts` in step.
- API permissions: every view states its `permission_classes` (`IsGlobalAdmin`,
  `IsGlobalAdminOrReadOnly` or `HasDeviceGroupPermission('<flag>')` from `accounts/access.py`,
  a test enforces it), and querysets are filtered with `access.devices_for(...)` and friends so
  hidden objects 404; never rely on the UI hiding something, and never check `is_staff`/`is_superuser`.
  Authentication is the Django session (CSRF on unsafe methods). Secrets in serializers are
  write-only for everyone. Audit security-relevant actions with `audit.log.record(...)`.
- Frontend: `<script setup lang="ts">` only (ESLint enforces it); strict TypeScript
  (`make frontend-lint` runs ESLint and vue-tsc). Import via the `@/` alias. Admin CRUD
  pages use `useCrud` + `FormDialog` + `PageCard`; show API errors with
  `useNotify().error(err, fallback)`. Never render untrusted text with `v-html`.
  Tests are Vitest specs next to the code (`*.spec.ts`).
- Workers and receivers must not import Django. The orchestrator owns all database access; workers
  and receivers communicate only through RabbitMQ and Redis.
- Everything the orchestrator sends a worker is signed: wrap task parameters with
  `core.signing.sign_task(...)` and have the worker task call `verified_payload(...)`
  first. Never add an unsigned task or a worker-side config setting; workers get
  configuration only through their assignment.
- Backup methods shown or accepted by the API come from `core.workers.driver_catalogue()`
  (what approved collectors advertise), not from worker code.
- Collector drivers subclass `CollectorDriver` (`worker/src/devicevault_worker/drivers/base.py`)
  with a pydantic `Params` model, and raise `TransientError` (retried) or `PermanentError`.
  SSH CLI platforms subclass `drivers.ssh.NetmikoDriver` (a Netmiko `device_type`, the
  commands, and regexes for volatile lines); see `drivers/cisco.py`. Built-ins are listed in
  `drivers/__init__.py`; third-party drivers register under the
  `devicevault.collectors` entry point. Storage drivers subclass `storage.drivers.base.StorageDriver` (see `storage/drivers/local.py`, `s3.py`), stream
  content (`store` reads a binary file, `read` writes one; backups can be hundreds of MB) and register under
  `devicevault.storage`; mark secret settings `SecretStr` so the API treats them as write-only.
- Secrets sent to workers go through `core.keys.add_secret` (sealed per worker when payload
  encryption is on) and come out through `devicevault_worker.payload.secret`. Secret model
  fields use `core.fields.EncryptedJSONField`.
- Backups are `backups.models.BackupJob`s: create them with `backups.jobs.create_job`, and let
  worker events drive their state (`backups.jobs.handle_job_event`). Never trust a worker's
  claim without checking its signature and approval.
- Retention deletes stored content only through `backups.retention` (signed `storage.delete`, confirmed by a
  `deleted` event); a pruned job row stays as the record. Anything that deletes backups must skip pinned ones
  (`BackupJob.pinned`) and keep the newest `min_backups`.
- Change summaries (`backups.changes`) run in the `events` process as a signed internal task, never inline in
  event handling. Collector drivers that produce noisy lines set `volatile_lines`, which the orchestrator also uses
  to compare pushed files.
- Config search (`search`) never indexes a secret value: drivers whose output holds secrets declare `secret_lines`
  (regex groups, optional `cisco7`-style encodings the orchestrator decodes), and those values are kept only as
  keyed tokens. Search results are filtered with `access.devices_for(user, 'view_contents')` in the query.
- Configuration is `DV_*` environment variables read through `devicevault_protocol.env`;
  never add config files. Document new variables in `docs/DEPLOYMENT.md` and the
  relevant `*.env.example`.
