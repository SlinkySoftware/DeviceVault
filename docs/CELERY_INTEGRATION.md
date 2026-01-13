# Celery Integration — DeviceVault

This document summarizes the Celery integration added to DeviceVault for distributed device collection.

## Overview
- A Celery application is initialized in `backend/devicevault_worker.py`.
- Collectors (backup plugins) under `backend/backups/plugins/` conform to a small contract: they accept a `config` dict and optional `timeout`, and return a structured dict with the keys `task_id`, `status`, `timestamp`, `log`, and `device_config`.
- The Celery task `device.collect` executes plugin code, enforces per-device locking via Redis, publishes the structured result to a Redis Stream (`device:results`), and returns the structured result; a separate Django consumer persists `DeviceBackupResult` rows.

## Routing Rules
- Each `CollectionGroup` record contains `rabbitmq_queue_id`.
- Queue name convention used by the worker and API: `collector.group.<rabbitmq_queue_id>`
- When enqueuing a task (API: `POST /api/devices/{id}/collect/`), the API chooses the queue as follows:
  - If `device.collection_group` is set, route to `collector.group.<rabbitmq_queue_id>`
  - Otherwise, do not specify a queue and let the broker deliver it to any available worker
- Implementation note: dynamic routing is applied at enqueue time using `celery_app.send_task(..., queue=<queue_name>)`.

## Scheduling Semantics
- DeviceVault retains scheduling in Django models (`BackupSchedule`) and related UI.
- We recommend using Celery Beat backed by Django schedule models for dynamic end-user defined schedules, because:
  - Celery Beat can drive regular periodic tasks while Celery workers perform the work.
  - Django models give users a UI and API to edit schedules at runtime.
  - Beat is the idiomatic, scalable approach compared with ad-hoc HTTP triggers.
- The current integration provides the task entrypoint and dynamic enqueue helpers; adding Celery Beat integration (e.g., django-celery-beat) is a follow-up step.

## Locking Model — Per-Device Concurrency
- We use Redis locks (redis-py `Lock`) with keys `lock:device:<device_id>`.
- Lock timeout is set to `task_timeout + safety_margin` to avoid overlapping runs when tasks overrun or stall.
- If a task cannot acquire the lock, the enqueue returns a failure response and the existing worker logs contention.
- Rationale: Redis-based distributed locking is lightweight and works across worker processes and hosts.

## Result Storage & Retrieval
- A new ORM model `DeviceBackupResult` stores metadata about runs:
  - `task_id`, `task_identifier`, `device`, `status`, `timestamp`, `log` (JSON serialized list)
- Raw `device_config` is NOT stored on the ORM model — storage backends (e.g., Git/S3) should persist artifacts and use `task_identifier` to correlate.

## Reliability & Failure Handling
- Celery task is configured with `soft_time_limit` and `time_limit` and will autoretry with exponential backoff on exceptions.
- Soft time limits, revocation, and structured exception capture are handled in the task wrapper.

## Logging & Observability
- Workers produce structured JSON logs using `python-json-logger`.
- To run Flower locally for debugging:

```bash
# from repository root
source .venv/bin/activate
cd backend
celery -A celery_app flower --broker-api=http://guest:guest@localhost:15672/api/ --address=0.0.0.0 --port=5555
```

Note: The `--broker-api` argument tells Flower where the RabbitMQ management API is located (port 15672), allowing it to query broker statistics correctly.

- Example log snippet (JSON):

```
{"asctime": "2026-01-09T10:00:00Z", "levelname": "INFO", "name": "devicevault.worker", "message": "starting_collection", "device_id": 7, "plugin": "mikrotik_ssh_export"}
```

- Credentials are masked in logs where possible (passwords replaced with `****`).

## Developer Validation
Manual steps to validate changes locally:

1. Activate the repository virtualenv and install dependencies, then change into the backend folder:

```bash
# from repository root
source .venv/bin/activate && cd backend && pip install -r requirements.txt
```

2. Run migrations to add the `DeviceBackupResult` model:

```bash
# from repository root
source .venv/bin/activate && cd backend && python manage.py makemigrations devices
source .venv/bin/activate && cd backend && python manage.py migrate
```

3. Start a worker (single-process) for local testing:

```bash
# from repository root
source .venv/bin/activate && cd backend && celery -A devicevault_worker.app worker --loglevel=info
```

4. Enqueue a task via the API (requires auth):

```bash
# Example: trigger collection for device id 1
curl -X POST -H "Authorization: Token <token>" http://localhost:8000/api/devices/1/collect/
```

5. Inspect logs and check `DeviceBackupResult` entries in Django admin or via `manage.py shell`. 

## Notes & Next Steps
- This change provides the task entrypoint, locking, routing, and plugin contract. Next steps (separate PRs) could include:
  - Integrating `django-celery-beat` for direct UI-driven scheduled task management
  - Adding storage backends to persist `device_config` artifacts and reference them by `task_identifier`
  - Adding role-based visibility into job history in the frontend

*** End of summary
