"""
DeviceVault Celery Integration: Distributed Device Backup Collection

Architecture Overview
=====================

DeviceVault now uses Celery for distributed, asynchronous device backup collection.
The system includes:

1. Collector Plugins: Conform to a common Celery collection contract
   - Structured exception handling (authentication, timeout, plugin errors)
   - Configurable timeout per collection
   - JSON-serializable configuration and results
   - Support for arbitrary plugin-specific parameters

2. Task Routing: Celery tasks routed to workers based on collection groups
   - Default queue: collector.default (any available worker)
   - Collection group queues: collector.group.<group_name>
   - Dynamic routing: Device → CollectionGroup → Celery Queue → Worker Node

3. Per-Device Locking: Redis-backed distributed locks prevent concurrent collection
   - Lock key format: lock:device:<device_id>
   - Lock timeout: 1 hour (configurable)
   - Contention logging and graceful failure

4. Result Storage: ORM records + external device configuration storage
   - DeviceBackupResult: Metadata (task_id, task_identifier, status, logs)
   - Device config: Stored externally via FileSystemStorage or cloud backends
   - task_identifier: Stable reference for later config retrieval

5. Structured Logging: JSON logging with task context
   - Centralized log aggregation ready
   - Per-operation tracking (lock, plugin, storage, result)
   - Duration metrics for performance analysis

6. Reliability: Retries with exponential backoff, timeouts, revocation support
   - Task max retries: 3 (configurable in settings.CELERY_TASK_ROUTES)
   - Hard timeout: 30 minutes (settings.CELERY_TASK_TIME_LIMIT)
   - Soft timeout: 25 minutes (raises SoftTimeLimitExceeded)


Infrastructure Setup
====================

1. Dependencies (added to requirements.txt):
   - celery>=5.3.0
   - redis>=4.5.0
   - django-celery-beat>=2.5.0
   - django-celery-results>=2.5.0
   - python-json-logger>=2.0.7
   - flower>=2.0.0 (debugging only)

2. Django Settings (devicevault/settings.py):
   - INSTALLED_APPS: Added 'django_celery_beat', 'django_celery_results'
   - CELERY_BROKER_URL: Redis connection (default: redis://localhost:6379/0)
   - CELERY_RESULT_BACKEND: Redis connection (default: redis://localhost:6379/1)
   - Task routing: CELERY_TASK_ROUTES, CELERY_QUEUES, CELERY_DEFAULT_QUEUE
   - Timeouts: CELERY_TASK_SOFT_TIME_LIMIT, CELERY_TASK_TIME_LIMIT

3. Database Models:
   - CollectionGroup: Defines task routing groups (new)
   - Device.collection_group: ForeignKey to CollectionGroup (new)
   - DeviceBackupResult: Stores collection task metadata (new)


Collection Task Execution Flow
==============================

1. Trigger:
   Via API endpoint: POST /api/devices/{id}/trigger_collection/
   
   Request:
   {
     "timeout": 30  // Optional, seconds
   }
   
   Response:
   {
     "task_id": "celery-uuid",
     "status": "pending",
     "device_id": 5,
     "queue": "collector.default"
   }

2. Queue Assignment:
   If device.collection_group is set:
     queue = "collector.group.<group_name>"
   Else:
     queue = "collector.default"

3. Task Execution (celery_app.device_collect_task):
   
   a) Lock Acquisition:
      acquire_device_lock(device_id, timeout=3600)
      - SET lock:device:<id> <timestamp> NX EX 3600
      - If lock held, return failure immediately
      - Log: [Lock] Acquired lock for device X
   
   b) Device & Plugin Validation:
      - Load device from ORM
      - Get backup plugin by device.backup_method
      - Load collection config from request
      - Log: [Device] Loaded device: X, [Plugin] Using: Y
   
   c) Plugin Execution:
      result = plugin.collect_async(config, timeout=30, task_id=task_id)
      
      Returns:
      {
        "task_id": "<task_id>",
        "status": "success|failure",
        "timestamp": "<iso8601>",
        "log": ["<messages>"],
        "device_config_ref": None,
        "_raw_device_config": "<config text>"
      }
      
      Exceptions raised by plugin are caught and returned as failure JSON.
      Log: [Plugin] Plugin execution completed/failed
   
   d) External Storage:
      If result['status'] == 'success' and device_config exists:
        storage = FileSystemStorage(base_path='backups')
        device_config_ref = storage.save(
          f"{device.name}/{device.backup_method}/{device.device_type.name}/{device.id}.cfg",
          device_config
        )
        Log: [Storage] Device config saved to <path>
   
   e) ORM Result Record:
      task_identifier = f"{device_id}:{task_id}"
      
      DeviceBackupResult.objects.create(
        task_id=task_id,
        task_identifier=task_identifier,
        device=device,
        status=result['status'],
        timestamp=now(),
        log=json.dumps(log_messages)
      )
      Log: [Result] Created DeviceBackupResult record
      
      Update device.last_backup_time, device.last_backup_status
   
   f) Lock Release:
      release_device_lock(lock_key)
      Log: [Lock] Released lock for device X
   
   Return:
   {
     "task_id": "<celery_uuid>",
     "status": "success|failure",
     "timestamp": "<iso8601>",
     "log": ["<all_messages>"],
     "device_config_ref": "<storage_path or None>",
     "task_identifier": "<device_id:task_id>"
   }

4. Lock Contention Handling:
   
   If a new collection task tries to acquire lock already held:
     - Lock acquisition fails immediately
     - Task returns failure JSON
     - Log: [Lock] Lock contention for device X: held by <timestamp>
     - No retry is attempted (device already being collected)
     - Client queries result status via /api/device-backup-results/{id}/

5. Failure Scenarios (all handled gracefully):
   
   a) SSH Connection Timeout (plugin timeout):
      - Plugin raises CollectorTimeoutException
      - Caught in collect_async, returns failure JSON
      - Log: [Plugin] Timeout: SSH connection to 192.168.1.1 timed out after 30s
      - Status: failure
   
   b) Authentication Failure:
      - Plugin raises CollectorAuthException
      - Caught in collect_async, returns failure JSON
      - Log: [Plugin] Authentication failed: SSH auth error
      - Status: failure
   
   c) Plugin Command Error:
      - Plugin raises CollectorPluginException
      - Caught in collect_async, returns failure JSON
      - Log: [Plugin] Collection error: /export command failed
      - Status: failure
   
   d) Storage Failure:
      - FileSystemStorage.save() raises exception
      - Caught in task, logged with traceback
      - Status: failure
      - Result record still created (for audit trail)
   
   e) Unhandled Exception:
      - Caught at task level
      - Full traceback logged
      - Status: failure
      - Result record created


Simulated Stale Task Demonstration
===================================

The device_collect_stale_task is used to demonstrate lock contention:

1. Start stale task:
   celery_app.device_collect_stale_task.apply_async(args=[5])
   - Acquires lock for device 5
   - Sleeps 60 seconds (simulates stuck task)
   - Releases lock

2. Try collection during stale task:
   device_collect_task.apply_async(args=[5, config_json, None])
   - Attempts to acquire same lock
   - Lock acquisition fails
   - Task returns: {
       "status": "failure",
       "log": ["Failed to acquire lock for device 5 - another collection in progress"]
     }

3. Manual cleanup (if needed):
   redis_client.delete("lock:device:5")


Retrieving Device Configurations
=================================

Device configurations are stored externally, not in the ORM.

To retrieve a device config after successful collection:

1. Query for the collection result:
   GET /api/device-backup-results/?device_id=5&status=success
   
   Response includes task_identifier: "5:celery-uuid"

2. Use task_identifier to retrieve from storage:
   storage = FileSystemStorage(base_path='backups')
   config = storage.retrieve("backups/device_name/method/type/5.cfg")
   
   OR via the model helper:
   result = DeviceBackupResult.objects.get(task_identifier="5:celery-uuid")
   storage_ref = result.get_device_config_ref()
   config = storage.retrieve(storage_ref)


Local Development Workflow
==========================

1. Install dependencies:
   pip install -r backend/requirements.txt

2. Start Redis (required for Celery broker and locks):
   redis-server
   # Or in Docker: docker run -p 6379:6379 redis:latest

3. Run Django development server:
   cd backend
   python3 manage.py runserver

4. Start Celery worker:
   celery -A devicevault worker -l info -Q collector.default,scheduler
   
   Start multiple workers for specific collection groups:
   celery -A devicevault worker -l info -Q collector.group.us-west
   celery -A devicevault worker -l info -Q collector.group.eu-east

5. Optional: Start Celery Beat for periodic scheduling:
   celery -A devicevault beat -l info
   
   (Configure periodic tasks via Django admin or BackupSchedule model)

6. Optional: Monitor with Flower:
   celery -A devicevault flower --port=5555
   # Access: http://localhost:5555/
   
   WARNING: Flower is for development/debugging only. Do not expose to production networks.


Configuration Reference
=======================

settings.py Celery Settings:

CELERY_BROKER_URL
  Type: str
  Default: "redis://localhost:6379/0"
  Purpose: Celery message broker (RabbitMQ, Redis, etc.)
  Env var: CELERY_BROKER_URL

CELERY_RESULT_BACKEND
  Type: str
  Default: "redis://localhost:6379/1"
  Purpose: Celery result storage backend
  Env var: CELERY_RESULT_BACKEND

CELERY_TASK_TIME_LIMIT
  Type: int (seconds)
  Default: 1800 (30 minutes)
  Purpose: Hard timeout - task killed if not complete
  
CELERY_TASK_SOFT_TIME_LIMIT
  Type: int (seconds)
  Default: 1500 (25 minutes)
  Purpose: Soft timeout - raises SoftTimeLimitExceeded signal

CELERY_TASK_ROUTES
  Type: dict
  Purpose: Task → queue routing rules
  Example:
    {
      'device.collect': {'queue': 'collector.default'},
      'device.collect.stale': {'queue': 'collector.default'},
    }

CELERY_QUEUES
  Type: dict
  Purpose: Define available queues and exchange bindings
  Example:
    {
      'collector.default': {
        'exchange': 'collector',
        'routing_key': 'collector.default',
      },
      'scheduler': {...}
    }

redis Lock Parameters (in celery_app.py):

acquire_device_lock(device_id, timeout=3600):
  - Lock key: "lock:device:<device_id>"
  - Lock timeout: 3600 seconds (1 hour)
  - Prevents concurrent collection for same device
  - Returns (acquired: bool, lock_key: str)


API Endpoints
=============

Trigger Collection:
  POST /api/devices/{device_id}/trigger_collection/
  Body (optional): {"timeout": 30}
  Response: {
    "task_id": "celery-uuid",
    "status": "pending",
    "device_id": 5,
    "queue": "collector.default"
  }

List Collection Results:
  GET /api/device-backup-results/
  Filters: ?device_id=5&status=success&task_id=celery-uuid
  Response: [
    {
      "id": 42,
      "task_id": "celery-uuid",
      "task_identifier": "5:celery-uuid",
      "device": 5,
      "status": "success",
      "timestamp": "2026-01-08T10:15:43.456Z",
      "log": ["[Lock] Acquired...", "[Plugin] Execution complete..."]
    },
    ...
  ]

Get Collection Result:
  GET /api/device-backup-results/{id}/
  Response: {...same as above...}


Structured Logging Examples
============================

Example 1: Successful Collection
{
  "timestamp": "2026-01-08T10:15:43.456Z",
  "level": "INFO",
  "service": "devicevault-worker",
  "task_id": "abc123def456",
  "device_id": 5,
  "message": "[Lock] Acquired lock for device 5"
}

Example 2: Lock Contention
{
  "timestamp": "2026-01-08T10:15:44.789Z",
  "level": "WARNING",
  "service": "devicevault-worker",
  "task_id": "def456abc123",
  "device_id": 5,
  "message": "[Lock] Lock contention for device 5: held by 2026-01-08T10:15:30.000Z"
}

Example 3: Plugin Timeout
{
  "timestamp": "2026-01-08T10:15:50.000Z",
  "level": "ERROR",
  "service": "devicevault-worker",
  "task_id": "abc123def456",
  "device_id": 5,
  "message": "[Plugin] Timeout: SSH connection to 192.168.1.1 timed out after 30s"
}


Testing & Validation
====================

Manual Testing:

1. Create a test device via Django admin
   - Set backup_method to 'mikrotik_ssh_export' or 'noop'
   - Add SSH credentials
   - Optionally assign to a collection_group

2. Trigger collection via API:
   curl -X POST http://localhost:8000/api/devices/1/trigger_collection/ \
     -H "Authorization: Token <token>" \
     -H "Content-Type: application/json" \
     -d '{"timeout": 30}'

3. Monitor Celery worker logs
   Check worker console for [Lock], [Plugin], [Storage], [Result] messages

4. Query results:
   curl http://localhost:8000/api/device-backup-results/?device_id=1 \
     -H "Authorization: Token <token>"

5. Verify external storage:
   ls -la backups/
   # Should contain: backups/<device_name>/<method>/<type>/<device_id>.cfg

Failure Simulation:

1. Timeout:
   Use a device with an unreachable IP
   - Plugin will timeout after configured timeout seconds
   - DeviceBackupResult will have status='failure'

2. Auth failure:
   Use incorrect credentials in device.credential
   - Plugin will raise CollectorAuthException
   - DeviceBackupResult will have status='failure'

3. Lock contention:
   Start device_collect_stale_task, then trigger collection
   - Second task will fail to acquire lock
   - Return failure immediately without retrying


Database Schema Notes
====================

CollectionGroup:
  - name: Unique identifier (e.g., "us-west-collectors")
  - queue_name: Auto-derived Celery queue name
  - Allows routing device collections to specific worker nodes

Device:
  + collection_group: ForeignKey (nullable, optional)
  - Devices without collection_group route to collector.default queue

DeviceBackupResult:
  - task_id: Celery task UUID (db_index=True)
  - task_identifier: Stable reference for config storage
    Format: "{device_id}:{task_id}"
    Used to retrieve device config from external storage
  - device: ForeignKey to Device (db_index=True, cascade delete)
  - status: success|failure|pending|revoked
  - timestamp: When task completed
  - log: JSON-serialized list of operation log messages
  
  Indices:
    - task_id: Fast lookup by Celery UUID
    - task_identifier: Fast lookup for config retrieval
    - device: Fast lookup of all results for a device
    - -timestamp: Reverse chronological ordering


Scaling & Production Deployment
================================

Single Worker Node:
  celery -A devicevault worker -l info -Q collector.default,scheduler
  - Single worker handles all collection tasks
  - Suitable for <100 devices, <1000 collections/day

Multi-Worker Single Queue:
  # Start 3 workers on same node, same queue
  celery -A devicevault worker -l info -Q collector.default -c 4 --name=w1@%h
  celery -A devicevault worker -l info -Q collector.default -c 4 --name=w2@%h
  celery -A devicevault worker -l info -Q collector.default -c 4 --name=w3@%h
  - Concurrency (-c): 4 tasks per worker
  - Total: 12 concurrent collections

Multi-Queue with Collection Groups:
  # Worker 1: US region devices
  celery -A devicevault worker -l info -Q collector.group.us-west,collector.default
  
  # Worker 2: EU region devices
  celery -A devicevault worker -l info -Q collector.group.eu-east,collector.default
  
  # Worker 3: Asia region devices
  celery -A devicevault worker -l info -Q collector.group.asia-sg,collector.default
  
  Devices assigned to collection groups are routed to specific workers
  Ensures geographic locality, compliance, and load distribution

Monitoring:
  - Flower: Real-time task monitoring, worker metrics
  - Prometheus/Grafana: Export Celery metrics via django-prometheus
  - Structured logs: Ship JSON logs to ELK/Datadog/CloudWatch
  - Django admin: View DeviceBackupResult for past collections
  - Alert on task failures, long durations, lock contention

Database:
  - PostgreSQL for production (not SQLite)
  - Index on DeviceBackupResult.device for fast filtering
  - Index on DeviceBackupResult.task_identifier for config lookup

Redis:
  - Use external Redis instance (not localhost)
  - Configure persistence (RDB snapshots or AOF)
  - Set maxmemory policy: allkeys-lru
  - Monitor: redis-cli INFO memory, MONITOR


Troubleshooting
===============

Celery Tasks Not Running:

1. Check Redis connectivity:
   redis-cli ping
   # Should return: PONG

2. Check Celery worker status:
   celery -A devicevault inspect active
   # Should list any active tasks

3. Check CELERY_BROKER_URL setting:
   python3 manage.py shell
   >>> from django.conf import settings
   >>> print(settings.CELERY_BROKER_URL)

4. Check Django logs for import errors:
   python3 manage.py shell
   >>> from celery_app import device_collect_task
   # Should import without errors

Locks Not Being Acquired:

1. Check Redis lock status:
   redis-cli
   > KEYS lock:device:*
   > GET lock:device:5
   # Shows lock timestamp or (nil) if free

2. Manually clear stuck lock:
   redis-cli
   > DEL lock:device:5

Device Config Not Stored:

1. Check storage backend configuration:
   python3 manage.py shell
   >>> from storage.fs import FileSystemStorage
   >>> s = FileSystemStorage(base_path='backups')
   >>> print(s.base_path)

2. Check filesystem permissions:
   ls -la backups/
   # Should be writable by Django process user

3. Check DeviceBackupResult.log for storage errors:
   python3 manage.py shell
   >>> from devices.models import DeviceBackupResult
   >>> r = DeviceBackupResult.objects.latest('timestamp')
   >>> print(r.get_log())

Task Timeouts:

1. Check task execution time:
   Query DeviceBackupResult, note collection duration
   If >25 minutes (CELERY_TASK_SOFT_TIME_LIMIT), increase limit in settings.py

2. Increase timeout:
   settings.py:
   CELERY_TASK_SOFT_TIME_LIMIT = 50 * 60  # 50 minutes
   CELERY_TASK_TIME_LIMIT = 55 * 60       # 55 minutes hard limit

3. Or increase per-collection:
   POST /api/devices/1/trigger_collection/ -d '{"timeout": 60}'

"""

# This docstring serves as reference documentation.
# For user-facing deployment guides, see docs/CELERY_DEPLOYMENT.md (TODO)
