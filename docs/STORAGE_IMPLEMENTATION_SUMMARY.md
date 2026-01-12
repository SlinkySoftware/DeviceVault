# Storage Pipeline Implementation Summary

## Files Created

1. **`backend/storage/tasks.py`** — Celery tasks for storage backends (store and read operations).
2. **`backend/devices/management/commands/consume_storage_results.py`** — Django management command to consume storage results from Redis stream.
3. **`backend/backups/storage_client.py`** — Synchronous helper for reading backups via storage workers.
4. **`docs/STORAGE_PIPELINE.md`** — Comprehensive documentation of the storage pipeline architecture.

## Files Modified

1. **`backend/storage/git.py`** — Refactored to expose `store_backup()` and `read_backup()` standalone functions.
2. **`backend/storage/fs.py`** — Refactored to expose `store_backup()` and `read_backup()` standalone functions.
3. **`backend/devices/management/commands/consume_device_results.py`** — Extended to dispatch storage tasks after successful backup collection.
4. **`backend/backups/models.py`** — Added `StoredBackup` ORM model.
5. **`backend/api/serializers.py`** — Added `StoredBackupSerializer`.
6. **`backend/api/views.py`** — Added `StoredBackupViewSet` with synchronous `download()` action.
7. **`backend/devicevault/urls.py`** — Registered `stored-backups` API endpoint.
8. **`backend/celery_app.py`** — Added `STORAGE_RESULTS_STREAM` configuration.
9. **`backend/devicevault/settings.py`** — Added `DEVICEVAULT_STORAGE_RESULTS_STREAM` setting.
10. **`README.md`** — Added link to storage pipeline documentation.

## Database Migration

- **`backend/backups/migrations/0005_add_stored_backup.py`** — Created via `makemigrations` for `StoredBackup` model.

## Key Features Implemented

### 1. Storage Worker Routing

- Storage tasks are routed to queue-specific workers:
  - `storage.git` for Git-based storage
  - `storage.fs` for filesystem-based storage
- Queue selection is based on the device's `backup_location.location_type`.

### 2. Standalone Storage Plugins

- `backend/storage/git.py` and `backend/storage/fs.py` no longer use classes.
- Expose two functions:
  - `store_backup(content, rel_path, config) -> storage_ref`
  - `read_backup(storage_ref, config) -> content`
- No Django imports; fully standalone for worker execution.

### 3. Storage Task Invocation

- After a successful device collection, `consume_device_results.py` dispatches a `storage.store` task.
- Task payload includes:
  - `device_config` (raw backup content)
  - `storage_backend` (e.g., `git` or `fs`)
  - `storage_config` (from `BackupLocation.config`)
  - `task_identifier` (logical job identifier)

### 4. Storage Results Persistence

- Storage workers publish results to the `storage:results` Redis stream.
- `consume_storage_results.py` reads this stream and writes to the `StoredBackup` table.
- The `StoredBackup` table is the authoritative index for backup retrieval.

### 5. Synchronous Backup Retrieval

- Frontend calls `GET /api/stored-backups/<id>/download/`.
- Django synchronously invokes `storage.read` task via `read_backup_via_worker()`.
- Worker returns raw backup content; Django streams it to the frontend as a file download.

### 6. Strict Separation of Concerns

- **Storage workers**: No Django imports. Standalone execution.
- **Django**: Owns all ORM writes. Owns Redis stream consumption. Owns orchestration only.

### 7. Reliability & Logging

- Celery tasks use `autoretry_for=(Exception,)` with exponential backoff.
- Structured JSON logging via `python-json-logger`.
- Storage failures are reported via Redis stream and visible in `StoredBackup` table.

## Developer Verification Steps (Summary)

1. **Create a backup location** (Git or filesystem) via Django admin or API.
2. **Assign the location to a device**.
3. **Trigger a backup** via frontend or API (`/api/devices/<id>/backup_now/`).
4. **Observe pipeline stages**:
   - Device collection result in `device:results` Redis stream
   - Storage task queued on `storage.git` or `storage.fs`
   - Storage result in `storage:results` Redis stream
5. **Verify database records**:
   - `DeviceBackupResult` for collection outcome
   - `StoredBackup` for storage outcome
6. **Test retrieval**: `GET /api/stored-backups/<id>/download/`
7. **Verify storage on disk**:
   - Git: `git log` in repo path
   - Filesystem: `ls` in base path

Full verification steps are in `docs/STORAGE_PIPELINE.md`.

## Technical Notes

- **Redis streams**: Used for asynchronous result consumption (idempotent via `task_identifier`).
- **RabbitMQ queues**: Used for Celery task routing (storage workers bind to specific queues).
- **Synchronous retrieval**: Uses `task.get(timeout=60)` to block until worker returns content.
- **Opaque storage refs**: Git backend returns `branch:path@commit`; filesystem backend returns `path`.
- **Type hints**: Added `# type: ignore` comments for Pylance false positives (redis-py, python-json-logger).

## Running the Storage Workers

Storage workers must be started separately from collector workers:

```bash
# Start a Git storage worker
celery -A celery_app worker -Q storage.git -n git-worker@%h --loglevel=info

# Start a filesystem storage worker
celery -A celery_app worker -Q storage.fs -n fs-worker@%h --loglevel=info
```

Or use a combined worker for development:

```bash
celery -A celery_app worker -Q storage.git,storage.fs -n storage-worker@%h --loglevel=info
```

## Next Steps

- **Production deployment**: Ensure storage workers have access to Git repos and filesystem mounts.
- **Monitoring**: Use Flower or Celery events to monitor storage task execution.
- **Frontend integration**: Update frontend to display storage status and enable download from `StoredBackup` records.
- **Testing**: Manual testing via Django shell and API calls (no unit tests per project conventions).
