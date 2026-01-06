<!-- Copilot / AI agent instructions for contributors and agents -->
# Copilot instructions — DeviceVault

Purpose: give AI coding agents the minimal, actionable context to be productive in this repository.

- **Big picture**: DeviceVault is a Django (backend) + Quasar/Vue (frontend) app that collects, stores, and compares network device backups. The orchestration scripts are at the repo root (`devicevault.sh`) and the Docker-based workflow is in `docker-build/` (see `Makefile`). The Django settings load runtime config from `backend/config/config.yaml`.

- **How the system is arranged**:
  - Backend: `backend/` — Django apps live in `core`, `devices`, `backups`, `credentials`, `locations`, `policies`, `rbac`, `audit`, `api`.
  - Frontend: `frontend/` — Quasar/Vue SPA; dev commands in `package.json` (`dev`, `build`).
  - Orchestration: `devicevault.sh` (root) is the recommended local developer entrypoint; `docker-build/docker-compose.yaml` and `docker-build/Makefile` provide container workflows.
  - Config: `backend/config/config.yaml` controls DB engine and local admin seed values; `backend/devicevault/settings.py` reads this file via `DEVICEVAULT_CONFIG`.

- **Key integration points** (where to look first):
  - API surface and serializers: `backend/api/` (views, serializers, permissions).
  - Background worker: `backend/devicevault_worker.py` and optional Celery config in `docker-build/`.
  - Storage backends: `backend/storage/git.py` and `backend/storage/fs.py` (how backups are persisted).
  - Connectors: `backend/connectors/ssh.py` (SSH collector patterns — follow the same auth/timeout style).

- **Common developer workflows & commands** (use these exact invocations):
  - Quick start (recommended): `./devicevault.sh start` — starts both frontend and backend for local development.
  - Docker-based: `make up` (from `docker-build/Makefile`) or `docker compose -f docker-compose.yaml up -d`.
  - Django management in containers: `make migrate` or `docker compose -f docker-compose.yaml run --rm django python3 manage.py migrate --run-syncdb`.
  - Frontend dev: `cd frontend && npm install && npm run dev` or `make watch-frontend` (Makefile target).

- **Project-specific conventions & patterns**:
  - Config-first: runtime behavior is driven by `backend/config/config.yaml`. Agents editing settings or DB code should check that YAML before changing defaults.
  - Pluggable storage: add new storage backends by following `backend/storage/git.py` interface (save, list, retrieve) and registering configuration via backup location models in `backups/`.
  - Device connectors follow a connector pattern in `backend/connectors/`; prefer reusing common helpers (timeouts, paramiko setup) to match existing error handling.
  - No strict type hints: codebase uses idiomatic Django 6 style without pervasive type annotations — keep patches minimal and consistent.

- **Where tests and verification live**:
  - There are no formal unit tests checked in; prefer manual verification using `./devicevault.sh` or Docker Compose `make up`, then use the UI or `manage.py shell` to validate data models.

- **Editing guidance / PR tips for agents**:
  - Small, focused changes only — modify one app/module per PR.
  - When changing default config values, update `backend/config/config.yaml` and `backend/devicevault/settings.py` if necessary.
  - For API changes, update `backend/api/serializers.py` and `backend/api/views.py` together and ensure the frontend `src/services/api.js` matches new endpoints.

- **Examples (copyable patterns)**:
  - Read config in settings: check `backend/devicevault/settings.py` for `CONFIG_PATH` loading.
  - Run migrations (local): `./devicevault.sh start` then `cd backend && python manage.py migrate --run-syncdb`.

If anything here is unclear or you'd like more detail about a specific area (connectors, storage, or the Docker-based workflow), tell me which part and I will expand or adjust this document.
