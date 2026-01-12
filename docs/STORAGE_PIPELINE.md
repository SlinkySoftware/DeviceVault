# Storage Pipeline Architecture

This document describes the **DeviceVault storage pipeline** where device backup collection results are offloaded to dedicated Celery storage workers for persistence, enabling strict worker routing, standalone execution, and full traceability.

## Overview

The storage pipeline is an asynchronous, multi-stage workflow that separates device collection from storage persistence:

1. **Collection stage**: A device backup is collected by a collector worker and published to the `device:results` Redis stream.
2. **Orchestration stage**: Django consumes `device:results` and writes collection outcomes to the database (`DeviceBackupResult`).
3. **Storage dispatch**: After a successful collection, Django enqueues a `storage.store` Celery task targeting the appropriate storage worker queue.
4. **Storage execution**: A storage worker receives the task, writes the backup to the configured storage backend (Git repo or filesystem), and publishes a result to the `storage:results` Redis stream.
5. **Storage consumption**: Django consumes `storage:results` and records the outcome in the `StoredBackup` table.
6. **Retrieval**: The frontend can request a backup download; Django synchronously calls a `storage.read` task on the correct worker queue and returns the backup content.

## Workflow: Collection → Storage → Retrieval

### 1. Device Collection (Existing)

- **Trigger**: User clicks "Backup Now" or a scheduled job runs.
- **Queue**: `collector.group.<rabbitmq_queue_id>` (device-specific collection group routing).
- **Task**: `device.collect` (Celery task defined in `backend/devicevault_worker.py`).
- **Output**: Device configuration is collected and published to the `device:results` Redis stream.

### 2. Collection Result Consumption

- **Consumer**: `backend/devices/management/commands/consume_device_results.py`
- **Behavior**:
  - Reads from the `device:results` Redis stream.
  - Persists the result to the `DeviceBackupResult` model.
  - **If the collection succeeded** (`status='success'`), it dispatches a `storage.store` task to the correct storage worker queue.

### 3. Storage Task (New)

- **Task**: `storage.store` (Celery task defined in `backend/storage/tasks.py`).
- **Queue routing**: Based on the device's configured `backup_location.location_type`:
  - `storage.git` for Git-based storage
  - `storage.fs` for filesystem-based storage
- **Payload**:
  ```json
  {
    "task_id": "<celery task id>",
    "task_identifier": "<logical backup job id>",
    "device_id": 123,
    "storage_backend": "git" | "fs",
    "storage_config": { /* location_type-specific config */ },
    "device_config": "<raw backup content>"
  }
  ```
- **Execution**:
  - Worker calls `storage.git.store_backup()` or `storage.fs.store_backup()` with the payload.
  - These functions are **standalone** (no Django ORM) and return an opaque `storage_ref` string.
  - Worker publishes the result to the `storage:results` Redis stream.
- **Output**:
  ```json
  {
    "task_id": "<celery task id>",
    "task_identifier": "<logical backup job id>",
    "device_id": 123,
    "storage_backend": "git",
    "storage_ref": "main:123/backup_now-123-2026-01-12T12-34-56Z.txt@abc123",
    "status": "success" | "failure",
    "timestamp": "2026-01-12T12:34:56.789Z",
    "log": ["stored to git:main:123/...@abc123"],
    "operation": "store"
  }
  ```

### 4. Storage Result Consumption (New)

- **Consumer**: `backend/devices/management/commands/consume_storage_results.py`
- **Behavior**:
  - Reads from the `storage:results` Redis stream.
  - Persists the result to the `StoredBackup` model (new ORM table).
  - This table is the authoritative index for retrieving backups.

### 5. Backup Retrieval (New)

- **API Endpoint**: `GET /api/stored-backups/<id>/download/`
- **ViewSet**: `StoredBackupViewSet.download()` (defined in `backend/api/views.py`).
- **Behavior**:
  - Looks up the `StoredBackup` record.
  - Calls the `read_backup_via_worker()` helper (defined in `backend/backups/storage_client.py`).
  - This sends a synchronous `storage.read` Celery task to the correct storage queue.
  - Waits for the result (blocking, with a 60-second timeout).
  - Returns the raw backup content as a text file download.

## Worker Routing Rationale

Storage backends are separated into dedicated queues for the following reasons:

- **Isolation**: Git workers may require access to specific Git repositories or network mounts. Filesystem workers may require specific directory mounts.
- **Firewall rules**: Different storage backends may be behind different firewall rules or VPNs.
- **Resource allocation**: Git workers may need more CPU for commit operations; filesystem workers may need more I/O.
- **Scaling**: Each storage backend can be scaled independently based on workload.

Queue naming convention:

- `storage.git` — for Git-based storage backends
- `storage.fs` — for filesystem-based storage backends

## Storage Backend Interface

Each storage backend (`backend/storage/git.py`, `backend/storage/fs.py`) exposes two functions:

### `store_backup(content: str, rel_path: str, config: dict) -> str`

Persists backup content to the storage backend and returns an opaque `storage_ref` string.

**Arguments:**

- `content`: Raw device configuration (string).
- `rel_path`: Suggested relative path for the backup file (e.g., `123/backup_now-123-2026-01-12T12-34-56Z.txt`).
- `config`: Storage-specific configuration (from `BackupLocation.config` JSON field).

**Returns:**

- `storage_ref` (string): Opaque identifier for later retrieval (e.g., `main:123/backup_now...@abc123` for Git).

**No Django dependencies:** These functions are standalone and do not import Django models or settings.

### `read_backup(storage_ref: str, config: dict) -> str`

Retrieves backup content from the storage backend.

**Arguments:**

- `storage_ref`: Opaque identifier returned by `store_backup()`.
- `config`: Storage-specific configuration.

**Returns:**

- Raw backup content (string).

## Synchronous vs Asynchronous Tasks

### Asynchronous (Fire-and-Forget)

- `device.collect` — Device collection tasks are fire-and-forget. Results are consumed asynchronously via Redis streams.
- `storage.store` — Storage tasks are fire-and-forget. Results are consumed asynchronously via Redis streams.

### Synchronous (Blocking)

- `storage.read` — Retrieval tasks are synchronous. Django calls `task.get(timeout=60)` to wait for the result. This ensures the frontend receives the backup content immediately for download.

## Data Models

### `DeviceBackupResult` (Existing)

Tracks the **collection** outcome for a device backup job.

**Fields:**

- `task_id` (str, indexed)
- `task_identifier` (str, indexed)
- `device` (FK to Device, indexed)
- `status` (str: `success` | `failure`)
- `timestamp` (datetime)
- `log` (JSON text)

### `StoredBackup` (New)

Tracks the **storage** outcome and location for a device backup.

**Fields:**

- `task_id` (str, indexed)
- `task_identifier` (str, indexed)
- `device` (FK to Device, indexed)
- `storage_backend` (str, indexed: `git` | `fs`)
- `storage_ref` (str: opaque identifier for retrieval)
- `status` (str: `success` | `failure`)
- `timestamp` (datetime)
- `log` (JSON text)

This table is the **authoritative index** for retrieving backups. It does not store the backup content itself.

## Configuration

### Redis Streams

- `DEVICEVAULT_RESULTS_STREAM` (default: `device:results`) — Device collection results.
- `DEVICEVAULT_STORAGE_RESULTS_STREAM` (default: `storage:results`) — Storage results.

### RabbitMQ Queues

- `collector.group.<rabbitmq_queue_id>` — Device collection tasks.
- `storage.git` — Git storage tasks.
- `storage.fs` — Filesystem storage tasks.

### Django Settings

- `DEVICEVAULT_REDIS_URL` — Redis connection URL (default: `redis://localhost:6379/1`).
- `DEVICEVAULT_RESULTS_STREAM` — Device collection results stream name.
- `DEVICEVAULT_STORAGE_RESULTS_STREAM` — Storage results stream name.

## Developer Verification Steps

### Prerequisites

- DeviceVault application running (`./devicevault.sh start` or `make up`).
- RabbitMQ and Redis accessible.
- At least one device configured with a backup location (Git or filesystem).

### Verification Steps

1. **Create a Git-based backup location** (via Django admin or API):
   ```json
   {
     "name": "Primary Git Repo",
     "location_type": "git",
     "config": {
       "repo_path": "/tmp/devicevault-git-repo",
       "branch": "main"
     }
   }
   ```

2. **Assign the backup location to a device** (via Django admin or API).

3. **Trigger a backup** (via frontend or API):
   ```bash
   curl -X POST http://localhost:8000/api/devices/1/backup_now/ \
     -H "Authorization: Token <your-token>" \
     -H "Content-Type: application/json"
   ```

4. **Observe the pipeline**:
   - **Collection**: Watch `device:results` Redis stream:
     ```bash
     redis-cli XREAD COUNT 10 STREAMS device:results 0
     ```
   - **Storage dispatch**: Check `consume_device_results.py` logs for "Storage task queued on storage.git".
   - **Storage execution**: Watch `storage:results` Redis stream:
     ```bash
     redis-cli XREAD COUNT 10 STREAMS storage:results 0
     ```
   - **Storage consumption**: Check `consume_storage_results.py` logs for "Persisted storage result".

5. **Verify database records**:
   ```bash
   cd backend && source ../.venv/bin/activate && python manage.py shell
   ```
   ```python
   from devices.models import DeviceBackupResult
   from backups.models import StoredBackup

   # Verify collection result
   DeviceBackupResult.objects.filter(device_id=1).order_by('-timestamp').first()

   # Verify storage result
   StoredBackup.objects.filter(device_id=1).order_by('-timestamp').first()
   ```

6. **Test backup retrieval**:
   ```bash
   curl -X GET http://localhost:8000/api/stored-backups/<id>/download/ \
     -H "Authorization: Token <your-token>" \
     -o backup.cfg
   ```

7. **Verify storage on disk**:
   - For Git: `cd /tmp/devicevault-git-repo && git log --oneline`
   - For filesystem: `ls -lh /tmp/devicevault-backups/`

## Failure Handling

- **Collection failures**: Recorded in `DeviceBackupResult` with `status='failure'`. No storage task is dispatched.
- **Storage failures**: Recorded in `StoredBackup` with `status='failure'`. The `log` field contains error messages.
- **Retrieval failures**: Return HTTP 500 with error details.

## Retry Logic

- **Collection**: Celery autoretry with exponential backoff (max 3 retries).
- **Storage**: Celery autoretry with exponential backoff (max 3 retries).
- **Retrieval**: No automatic retry; frontend can re-request.

## Logging

All storage tasks use structured JSON logging via `python-json-logger`. Example log entry:

```json
{
  "asctime": "2026-01-12T12:34:56.789Z",
  "levelname": "INFO",
  "name": "devicevault.storage.worker",
  "message": "storage_store_start",
  "storage_backend": "git",
  "device_id": 123,
  "task_identifier": "backup_now:123:2026-01-12T12:34:56.789Z",
  "queue": "storage.git"
}
```

## Summary

The storage pipeline separates device collection from storage persistence:

- **Device collection** is handled by collector workers (existing).
- **Storage persistence** is handled by dedicated storage workers (new).
- **Worker routing** ensures the correct storage backend is used (Git or filesystem).
- **Synchronous retrieval** enables the frontend to download backups on demand.
- **Full traceability** via `task_id` and `task_identifier` across all stages.

For more information, see:

- `backend/storage/tasks.py` — Storage Celery tasks
- `backend/storage/git.py` — Git storage backend
- `backend/storage/fs.py` — Filesystem storage backend
- `backend/devices/management/commands/consume_storage_results.py` — Storage result consumer
- `backend/backups/storage_client.py` — Synchronous retrieval helper
- `backend/api/views.py` — `StoredBackupViewSet` with `download()` action
*** End of File
