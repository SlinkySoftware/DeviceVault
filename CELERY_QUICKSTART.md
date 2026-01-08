# DeviceVault Celery Integration: Quick Start

## What Changed

DeviceVault now uses Celery for **distributed, asynchronous device backup collection**. Instead of the old APScheduler background scheduler, devices are collected via Celery tasks that can run on multiple worker nodes.

## Key Components Added

1. **celery_app.py** - Celery task definitions and routing
2. **celery_logging.py** - Structured JSON logging configuration
3. **Device.collection_group** - New ForeignKey for task routing
4. **CollectionGroup** model - Defines collector worker groups
5. **DeviceBackupResult** model - Stores task results with metadata
6. **API endpoint**: `POST /api/devices/{id}/trigger_collection/`
7. **API endpoint**: `GET /api/device-backup-results/` - Query task results
8. **Updated plugins** - Structured exceptions and async contract support

## Installation (Local Development)

### 1. Install Celery dependencies

```bash
pip install -r backend/requirements.txt
```

New packages:
- `celery>=5.3.0`
- `redis>=4.5.0`
- `django-celery-beat>=2.5.0`
- `django-celery-results>=2.5.0`
- `python-json-logger>=2.0.7`
- `flower>=2.0.0` (optional, for monitoring)

### 2. Start Redis broker

```bash
# Option A: System Redis
redis-server

# Option B: Docker
docker run -p 6379:6379 redis:latest
```

### 3. Run migrations

```bash
cd backend
python3 manage.py migrate
```

This creates the new `CollectionGroup` and `DeviceBackupResult` tables.

### 4. Start Django dev server

```bash
cd backend
python3 manage.py runserver
```

### 5. Start Celery worker

In a new terminal:

```bash
cd backend
celery -A devicevault worker -l info -Q collector.default,scheduler
```

You should see:
```
 -------------- celery@hostname v5.3.x --------
 --- ***** -----
 -- ******* ----
 - *** --- * ---
 - ** ---------- [config]
 - ** ---------- .broker:       redis://localhost:6379/0
 - ** ---------- .app:          devicevault:0x...
 - ** ---------- .concurrency:  4
...
[2026-01-08 10:00:00,000: WARNING/MainProcess] celery@hostname ready.
```

## Using the System

### 1. Create a Device (via Django admin)

- **Name**: `router-1`
- **IP Address**: `192.168.1.1`
- **Device Type**: Router
- **Backup Method**: `mikrotik_ssh_export` or `noop`
- **Credentials**: Add SSH username/password
- **Collection Group** (optional): Select a group for routing

### 2. Trigger a Collection

Via API:

```bash
curl -X POST http://localhost:8000/api/devices/1/trigger_collection/ \
  -H "Authorization: Token YOUR_TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"timeout": 30}'
```

Response:
```json
{
  "task_id": "abc123def456-7890abcd-efgh",
  "status": "pending",
  "device_id": 1,
  "queue": "collector.default"
}
```

### 3. Monitor Collection

Watch Celery worker output:
```
[2026-01-08 10:15:30,000: INFO/MainProcess] Task device.collect[abc123...] received
[2026-01-08 10:15:30,100: INFO/MainProcess] [Lock] Acquired lock for device 1
[2026-01-08 10:15:30,200: INFO/MainProcess] [Device] Loaded device: router-1
[2026-01-08 10:15:30,300: INFO/MainProcess] [Plugin] Using backup method: mikrotik_ssh_export
[2026-01-08 10:15:32,400: INFO/MainProcess] [Plugin] Device configuration retrieved successfully
[2026-01-08 10:15:32,500: INFO/MainProcess] [Storage] Device config saved to backups/router-1/mikrotik_ssh_export/Router/1.cfg
[2026-01-08 10:15:32,600: INFO/MainProcess] [Result] Created DeviceBackupResult record with task_identifier 1:abc123...
[2026-01-08 10:15:32,700: INFO/MainProcess] [Lock] Released lock for device 1
[2026-01-08 10:15:32,800: INFO/MainProcess] Task device.collect[abc123...] succeeded in 2.850s
```

### 4. Query Results

```bash
# Get all results
curl http://localhost:8000/api/device-backup-results/ \
  -H "Authorization: Token YOUR_TOKEN"

# Filter by device
curl http://localhost:8000/api/device-backup-results/?device_id=1 \
  -H "Authorization: Token YOUR_TOKEN"

# Filter by status
curl http://localhost:8000/api/device-backup-results/?status=success \
  -H "Authorization: Token YOUR_TOKEN"
```

Response:
```json
[
  {
    "id": 1,
    "task_id": "abc123def456-7890abcd-efgh",
    "task_identifier": "1:abc123def456-7890abcd-efgh",
    "device": 1,
    "status": "success",
    "timestamp": "2026-01-08T10:15:43.456Z",
    "log": [
      "[Lock] Acquired lock for device 1",
      "[Device] Loaded device: router-1",
      "[Plugin] Using backup method: mikrotik_ssh_export",
      "[Plugin] Device configuration retrieved successfully",
      "[Storage] Device config saved to backups/router-1/mikrotik_ssh_export/Router/1.cfg",
      "[Result] Created DeviceBackupResult record with task_identifier 1:abc123..."
    ]
  }
]
```

## How It Works

### Collection Groups & Routing

If you assign a device to a **CollectionGroup**, its collection tasks are routed to a specific queue:

```
Device.collection_group = "us-west-collectors"
           ↓
         routes to
           ↓
queue = "collector.group.us-west-collectors"
           ↓
         consumed by
           ↓
celery -A devicevault worker -Q collector.group.us-west-collectors
```

Devices without a collection group route to the default queue.

### Per-Device Locking

Only one collection task can run per device at a time, using Redis locks:

```
Task 1: device_collect_task(device_id=5)
  ↓ acquires lock:device:5
  ↓ collection runs
  ↓ releases lock:device:5

Task 2: device_collect_task(device_id=5)  [started during Task 1]
  ↓ tries to acquire lock:device:5
  ↓ lock already held
  ↓ returns failure immediately (no retry)
```

### Failure Handling

All failures are captured and returned as JSON:

- **SSH Connection Timeout** → status: failure, log includes timeout message
- **Authentication Error** → status: failure, log includes auth error
- **Plugin Command Error** → status: failure, log includes command output
- **Lock Contention** → status: failure, log: "another collection in progress"
- **Unexpected Error** → status: failure, log includes full traceback

Celery retries are automatic (up to 3 times with exponential backoff).

### External Config Storage

Device configurations are **not stored in the database**. Instead:

1. Plugin retrieves config from device
2. Config saved to filesystem: `backups/<device>/<method>/<type>/<id>.cfg`
3. DeviceBackupResult stores metadata + task_identifier
4. To retrieve config later: query by task_identifier, then read from filesystem

This approach:
- Keeps database size manageable
- Allows cloud storage backends (S3, Azure Blob, GCS)
- Enables versioning and archival policies

## Testing Failures

### Test Timeout

Use an unreachable device IP:

```python
# Django shell
from devices.models import Device
dev = Device.objects.create(
    name='unreachable',
    ip_address='10.255.255.255',  # Non-routable address
    backup_method='mikrotik_ssh_export',
    ...
)
# Trigger collection - will timeout after 30s
```

### Test Lock Contention

Use the stale task:

```bash
# Terminal 1: Start stale task (holds lock for 60 seconds)
python3 manage.py shell
>>> from celery_app import device_collect_stale_task
>>> device_collect_stale_task.apply_async(args=[1])

# Terminal 2: Try collection immediately
curl -X POST http://localhost:8000/api/devices/1/trigger_collection/ \
  -H "Authorization: Token YOUR_TOKEN"

# Task 2 will fail with: "another collection in progress"
```

### Test Auth Failure

Set wrong credentials:

```python
# Django admin: Device → Credentials
# Set username='wrong', password='wrong'
# Trigger collection - will fail with auth error
```

## Monitoring (Flower)

Optional web UI for task monitoring:

```bash
celery -A devicevault flower --port=5555
```

Access at: http://localhost:5555/

Features:
- Real-time task status and duration
- Worker pool statistics and activity
- Task history and results
- Rate limiting controls

⚠️ **Warning**: Flower is for development/debugging only. Do not expose to production.

## Docker Deployment

### docker-compose.yaml

```yaml
version: '3.8'
services:
  redis:
    image: redis:7-alpine
    ports:
      - "6379:6379"
    volumes:
      - redis_data:/data

  django:
    build: ./docker-build
    environment:
      CELERY_BROKER_URL: redis://redis:6379/0
    depends_on:
      - redis

  celery_worker:
    build: ./docker-build
    command: celery -A devicevault worker -l info -Q collector.default,scheduler
    environment:
      CELERY_BROKER_URL: redis://redis:6379/0
    depends_on:
      - redis

  celery_beat:
    build: ./docker-build
    command: celery -A devicevault beat -l info
    environment:
      CELERY_BROKER_URL: redis://redis:6379/0
    depends_on:
      - redis

volumes:
  redis_data:
```

Run:
```bash
docker-compose up -d
```

## Next Steps

1. **Celery Beat**: Set up periodic scheduling via `BackupSchedule` model
   - Configure devices to collect on a schedule
   - Uses `celery -A devicevault beat`

2. **Cloud Storage**: Configure S3, Azure Blob, or GCS for device configs
   - Update `storage/git.py` and `storage/fs.py` to support backends
   - Device configs stored remotely instead of locally

3. **Monitoring**: Set up centralized logging and alerting
   - Ship structured JSON logs to ELK, Datadog, CloudWatch
   - Alert on task failures, timeouts, or high concurrency

4. **Scaling**: Deploy multi-region worker nodes
   - Create collection groups per region
   - Assign devices to groups by geographic proximity
   - Deploy workers in each region on dedicated queues

## Troubleshooting

**Celery tasks not running?**
```bash
# Check Redis connectivity
redis-cli ping  # Should return PONG

# Check worker status
celery -A devicevault inspect active

# Check for import errors
python3 manage.py shell
>>> from celery_app import device_collect_task  # Should not error
```

**Locks stuck?**
```bash
# Check current locks
redis-cli KEYS lock:device:*

# Clear a specific lock
redis-cli DEL lock:device:5
```

**Config not being saved?**
```bash
# Check filesystem permissions
ls -la backups/
chmod 755 backups/

# Check storage in logs
python3 manage.py shell
>>> from devices.models import DeviceBackupResult
>>> r = DeviceBackupResult.objects.latest('timestamp')
>>> print(r.get_log())
```

## Architecture Summary

```
┌─────────────────┐
│  API Request    │
│ POST /trigger   │
└────────┬────────┘
         │
         v
┌─────────────────────┐
│  Validate Device    │
│  Build Config       │
└────────┬────────────┘
         │
         v
┌─────────────────────┐
│  Enqueue Task       │
│  to Celery Broker   │
│  (Redis)            │
└────────┬────────────┘
         │
         v
┌──────────────────────────────────────┐
│       Celery Worker                  │
│  ┌────────────────────────────────┐  │
│  │ 1. Acquire Lock (device:id)    │  │
│  │ 2. Run Plugin (ssh collect)    │  │
│  │ 3. Save Config (filesystem)    │  │
│  │ 4. Create ORM Result Record    │  │
│  │ 5. Release Lock                │  │
│  └────────────────────────────────┘  │
└──────────────────┬───────────────────┘
                   │
         ┌─────────┴──────────┐
         v                    v
    ┌─────────┐          ┌──────────────┐
    │   ORM   │          │ Filesystem   │
    │ Result  │          │   Config     │
    │ Metadata│          │    File      │
    └─────────┘          └──────────────┘
```

For detailed documentation, see [CELERY_INTEGRATION.md](../CELERY_INTEGRATION.md).
