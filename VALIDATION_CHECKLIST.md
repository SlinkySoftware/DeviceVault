# DeviceVault Celery Integration - Validation Checklist

## Pre-Deployment Validation

Use this checklist to verify the Celery integration is properly installed and working before deploying to production.

### 1. Dependencies Installation ✓

```bash
cd backend
pip install -r requirements.txt

# Verify installations
python3 -c "import celery; print(f'Celery: {celery.__version__}')"
python3 -c "import redis; print(f'Redis: {redis.__version__}')"
python3 -c "import django_celery_beat; print('django_celery_beat: OK')"
python3 -c "import django_celery_results; print('django_celery_results: OK')"
python3 -c "import pythonjsonlogger; print('python_json_logger: OK')"
python3 -c "import flower; print('flower: OK')"
```

### 2. Django Configuration ✓

```bash
cd backend
python3 manage.py shell

# In Django shell:
>>> from django.conf import settings
>>> print(f"Celery Broker: {settings.CELERY_BROKER_URL}")
>>> print(f"Celery Result Backend: {settings.CELERY_RESULT_BACKEND}")
>>> print(f"Task Time Limit: {settings.CELERY_TASK_TIME_LIMIT}")
>>> print(f"Task Soft Time Limit: {settings.CELERY_TASK_SOFT_TIME_LIMIT}")
>>> from celery_app import app
>>> print(f"Celery App: {app}")
>>> print(f"Celery Queues: {settings.CELERY_QUEUES}")
```

Expected:
- CELERY_BROKER_URL points to Redis
- CELERY_TASK_TIME_LIMIT = 1800 (30 minutes)
- CELERY_TASK_SOFT_TIME_LIMIT = 1500 (25 minutes)
- Celery app loads without errors

### 3. Database Migrations ✓

```bash
cd backend

# Check migration status
python3 manage.py showmigrations devices | grep -E "^devices"

# Expected output:
# [X] 0001_initial
# ...
# [X] 0013_ensure_devicegroup_tables
# [X] 0014_collectiongroup_device_collection_group_devicebackupresult

# If [X] next to 0014: ✓ Migrations applied
# If [ ] next to 0014: Run migrations
python3 manage.py migrate
```

Verify models exist:
```bash
python3 manage.py shell

>>> from devices.models import CollectionGroup, DeviceBackupResult
>>> print(f"CollectionGroup: {CollectionGroup._meta.db_table}")
>>> print(f"DeviceBackupResult: {DeviceBackupResult._meta.db_table}")
```

Expected:
- `CollectionGroup` table exists
- `DeviceBackupResult` table exists
- `Device.collection_group` foreign key exists

### 4. Redis Connectivity ✓

```bash
# In terminal, test Redis directly
redis-cli ping
# Expected response: PONG

redis-cli config get maxmemory
# Note maxmemory setting (should be set for production)

# Test from Django
python3 manage.py shell
>>> import redis
>>> r = redis.from_url('redis://localhost:6379/0')
>>> r.ping()
True
>>> r.set('test', 'value')
True
>>> r.get('test')
b'value'
>>> r.delete('test')
1
```

Expected: All Redis operations succeed without exception

### 5. Plugin Interface ✓

```bash
python3 manage.py shell

>>> from backups.plugins import get_plugin
>>> noop = get_plugin('noop')
>>> print(f"Noop plugin: {noop}")
>>> print(f"Has collect_async: {hasattr(noop, 'collect_async')}")

# Test async interface
>>> config = {'ip': '192.168.1.1', 'username': 'test', 'password': 'test', 'timeout': 30}
>>> result = noop.collect_async(config)
>>> print(f"Result status: {result['status']}")
>>> print(f"Result has task_id: {'task_id' in result}")
>>> print(f"Result has log: {'log' in result}")

# Test Mikrotik plugin (if available)
>>> mikrotik = get_plugin('mikrotik_ssh_export')
>>> print(f"Mikrotik plugin: {mikrotik}")
>>> print(f"Has collect_async: {hasattr(mikrotik, 'collect_async')}")
```

Expected:
- Plugins have `collect_async()` method
- Returns dict with keys: task_id, status, timestamp, log, device_config_ref
- Noop plugin succeeds immediately

### 6. Celery Task Import ✓

```bash
python3 manage.py shell

>>> from celery_app import app, device_collect_task, acquire_device_lock
>>> print(f"Celery app: {app}")
>>> print(f"Device collect task: {device_collect_task}")
>>> print(f"Task name: {device_collect_task.name}")
>>> print(f"Acquire lock function: {acquire_device_lock}")
```

Expected:
- Celery app initializes
- device_collect_task is registered
- Locking functions available

### 7. API Endpoints ✓

```bash
# Start Django dev server
python3 manage.py runserver

# In another terminal:
TOKEN="your-token-here"

# Verify device trigger endpoint exists
curl -X OPTIONS http://localhost:8000/api/devices/1/trigger_collection/ \
  -H "Authorization: Token $TOKEN"
# Should return 200 OK with allowed methods

# Verify device-backup-results endpoint exists
curl -X GET http://localhost:8000/api/device-backup-results/ \
  -H "Authorization: Token $TOKEN"
# Should return 200 OK with empty list (or existing results)
```

Expected:
- `/api/devices/{id}/trigger_collection/` responds to POST
- `/api/device-backup-results/` responds to GET
- Proper authentication required (401 without token)

### 8. Celery Worker Startup ✓

```bash
cd backend

# Start worker with verbose logging
celery -A devicevault worker -l debug -Q collector.default,scheduler

# Expected output:
# -------------- celery@hostname v5.x.x ----
# --- ***** -----
# -- ******* ----
# - *** --- * ---
# - ** ---------- [config]
# - ** ---------- .broker:       redis://localhost:6379/0
# - ** ---------- .app:          devicevault:0x...
# - ** ---------- .concurrency:  4 (or your worker count)
# - ** ---------- .max_tasks_per_child: unlimited
# ...
# [2026-01-08 10:00:00,000: WARNING/MainProcess] celery@hostname ready.
# [2026-01-08 10:00:00,100: INFO/MainProcess] Registered tasks: ['device.collect', ...]
```

Expected:
- Worker starts without errors
- Connected to Redis broker
- Tasks registered (device.collect, device.collect.stale, scheduling.list_pending)

### 9. Task Execution E2E ✓

```bash
# Create test device
python3 manage.py shell
>>> from devices.models import Device, DeviceType, CollectionGroup
>>> from credentials.models import Credential, CredentialType
>>> from locations.models import BackupLocation

>>> dtype = DeviceType.objects.get_or_create(name='Router')[0]
>>> cred_type = CredentialType.objects.get_or_create(name='SSH')[0]
>>> cred = Credential.objects.create(
...     name='test-cred',
...     credential_type=cred_type,
...     data={'username': 'test', 'password': 'test'}
... )
>>> location = BackupLocation.objects.get_or_create(name='Local')[0]
>>> device = Device.objects.create(
...     name='test-device',
...     ip_address='192.168.1.1',
...     device_type=dtype,
...     backup_method='noop',
...     credential=cred,
...     backup_location=location
... )
>>> print(f"Created device: {device}")
```

Trigger collection via API:
```bash
TOKEN="your-token-here"
DEVICE_ID=1

curl -X POST http://localhost:8000/api/devices/$DEVICE_ID/trigger_collection/ \
  -H "Authorization: Token $TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"timeout": 30}'

# Response should be:
# {
#   "task_id": "abc123...",
#   "status": "pending",
#   "device_id": 1,
#   "queue": "collector.default"
# }

TASK_ID="abc123..."  # Copy from response
```

Watch Celery worker output:
```bash
# Should see messages like:
# [2026-01-08 10:15:30,000: INFO/...] Task device.collect[abc123...] received
# [2026-01-08 10:15:30,050: INFO/...] [Lock] Acquired lock for device 1
# [2026-01-08 10:15:30,100: INFO/...] [Device] Loaded device: test-device
# [2026-01-08 10:15:30,150: INFO/...] [Plugin] Using backup method: noop
# [2026-01-08 10:15:30,200: INFO/...] [Plugin] Device configuration retrieved successfully
# [2026-01-08 10:15:30,250: INFO/...] [Result] Created DeviceBackupResult record
# [2026-01-08 10:15:30,300: INFO/...] [Lock] Released lock for device 1
# [2026-01-08 10:15:30,350: INFO/...] Task device.collect[abc123...] succeeded
```

Query results:
```bash
curl "http://localhost:8000/api/device-backup-results/?device_id=1" \
  -H "Authorization: Token $TOKEN"

# Should return:
# [
#   {
#     "id": 1,
#     "task_id": "abc123...",
#     "task_identifier": "1:abc123...",
#     "device": 1,
#     "status": "success",
#     "timestamp": "2026-01-08T10:15:30.300Z",
#     "log": [
#       "[Lock] Acquired lock for device 1",
#       "[Device] Loaded device: test-device",
#       ...
#     ]
#   }
# ]
```

Expected:
- Task enqueues and returns task_id
- Worker picks up task immediately
- Task completes with status='success'
- DeviceBackupResult created in database
- Result queryable via API

### 10. Lock Mechanism ✓

Test lock acquisition:
```bash
python3 manage.py shell

>>> from celery_app import acquire_device_lock, release_device_lock
>>> acquired, lock_key = acquire_device_lock(999)
>>> print(f"Lock acquired: {acquired}")
>>> print(f"Lock key: {lock_key}")

# Try to acquire same lock
>>> acquired2, lock_key2 = acquire_device_lock(999)
>>> print(f"Lock acquired (2nd attempt): {acquired2}")

# Release and retry
>>> release_device_lock(lock_key)
>>> acquired3, lock_key3 = acquire_device_lock(999)
>>> print(f"Lock acquired (after release): {acquired3}")
```

Expected:
- First acquisition: acquired=True
- Second acquisition: acquired=False (locked)
- After release: acquired=True (lock free)

### 11. Structured Logging ✓

Enable logging and collect a sample:
```bash
cd backend

# Start worker with logging
DEVICEVAULT_LOG_FILE=/tmp/celery.log celery -A devicevault worker -l info

# Trigger a collection (see section 9)

# Check log format
tail /tmp/celery.log | head -5
```

Expected output (formatted as JSON):
```json
{
  "timestamp": "2026-01-08T10:15:30.000Z",
  "level": "INFO",
  "service": "devicevault-worker",
  "logger": "celery_app",
  "message": "[Lock] Acquired lock for device 1"
}
```

### 12. Collection Group Routing ✓

Create a collection group:
```bash
python3 manage.py shell

>>> from devices.models import CollectionGroup, Device
>>> group = CollectionGroup.objects.create(
...     name='us-west',
...     description='US West collector workers'
... )
>>> print(f"Created group: {group}")
>>> print(f"Queue name: {group.queue_name}")

# Assign device to group
>>> device = Device.objects.get(id=1)
>>> device.collection_group = group
>>> device.save()
>>> print(f"Device {device.name} assigned to group {device.collection_group.name}")
```

Trigger collection and verify routing:
```bash
# Trigger collection for device 1
curl -X POST http://localhost:8000/api/devices/1/trigger_collection/ \
  -H "Authorization: Token $TOKEN"

# Response should show:
# "queue": "collector.group.us-west"

# Start worker for specific queue
celery -A devicevault worker -l info -Q collector.group.us-west

# Task will be routed to this worker only
```

Expected:
- CollectionGroup table created
- Device.collection_group ForeignKey works
- Queue name auto-derived: `collector.group.<group_name>`
- Tasks route to device's collection group queue

### 13. Failure Scenarios ✓

Test timeout:
```bash
# Create device with unreachable IP
python3 manage.py shell
>>> device = Device.objects.create(
...     name='timeout-test',
...     ip_address='10.255.255.255',
...     ...
... )

# Trigger collection
curl -X POST http://localhost:8000/api/devices/{id}/trigger_collection/ \
  -H "Authorization: Token $TOKEN" \
  -d '{"timeout": 5}'

# Wait 5+ seconds

# Query results - should be failure
curl http://localhost:8000/api/device-backup-results/?device_id={id} \
  -H "Authorization: Token $TOKEN"

# Log should contain timeout message
```

Test lock contention:
```python
python3 manage.py shell

>>> from celery_app import device_collect_stale_task
>>> device_collect_stale_task.apply_async(args=[1])  # Holds lock 60s

# In another terminal, trigger collection
curl -X POST http://localhost:8000/api/devices/1/trigger_collection/ \
  -H "Authorization: Token $TOKEN"

# Second task should fail immediately with lock contention message
```

Expected:
- Timeout: Result with status='failure', log includes timeout message
- Lock contention: Result with status='failure', log includes "another collection in progress"
- No exceptions raised; all failures returned as JSON

### 14. Flower Monitoring (Optional) ✓

```bash
# Start Flower
celery -A devicevault flower --port=5555

# Access web UI
open http://localhost:5555/

# Features to verify:
# - Task history shows all executed tasks
# - Worker pool shows active workers and concurrency
# - Task detail view shows arguments and results
# - Real-time task execution tracking
```

Expected:
- Flower UI loads at localhost:5555
- Shows all celery workers and active tasks
- Task history grows as collections run

---

## Production Deployment Checklist

Before deploying to production, verify:

- [ ] Redis configured with persistence (RDB snapshots or AOF)
- [ ] Redis configured with maxmemory policy (allkeys-lru)
- [ ] Redis replication/clustering for high availability
- [ ] Multiple Celery workers deployed (minimum 3)
- [ ] Worker auto-restart configured (systemd, supervisor, or container orchestration)
- [ ] Structured logs shipped to centralized logging (ELK, Datadog, CloudWatch)
- [ ] Alerts configured for:
  - Task failures (status='failure' in DeviceBackupResult)
  - Task timeouts (duration > CELERY_TASK_SOFT_TIME_LIMIT)
  - Worker offline (celery inspect stats fails)
  - Redis connectivity issues
  - Lock contention spike (> 10% of tasks failing on lock)
- [ ] Database backed up regularly
- [ ] DeviceBackupResult pruned on retention policy (old results deleted)
- [ ] Flower disabled or behind firewall (not publicly accessible)
- [ ] Load testing done with expected device count
- [ ] Disaster recovery plan tested (restore from backup, restart workers)

---

## Troubleshooting Quick Reference

| Issue | Symptom | Check | Fix |
|-------|---------|-------|-----|
| Redis unavailable | Task hangs, no activity | `redis-cli ping` | Start Redis, check connection string |
| Worker not running | Tasks queue but don't execute | `celery inspect active` | Start worker process |
| Task not found | "Task not found" error | Import celery_app | Restart worker after code changes |
| Lock stuck | Collections fail with lock contention | `redis-cli GET lock:device:X` | `redis-cli DEL lock:device:X` |
| Config not saved | DeviceBackupResult success but no file | `ls backups/` | Check permissions, filesystem full |
| Timeout too short | Collections timeout when they should succeed | Check task duration | Increase CELERY_TASK_TIME_LIMIT |
| Queue not consumed | Task enqueued but never picked up | `celery inspect active_queues` | Start worker for queue name |

---

## Sign-Off Checklist

- [ ] All 14 validation steps passed
- [ ] E2E test successful (section 9)
- [ ] Lock mechanism verified (section 10)
- [ ] Structured logging working (section 11)
- [ ] Collection group routing verified (section 12)
- [ ] Failure scenarios tested (section 13)
- [ ] Production environment prepared (if applicable)
- [ ] Team trained on new Celery system
- [ ] Documentation reviewed and understood
- [ ] Rollback plan documented and tested

---

## Support

For issues not covered in this checklist:

1. Check [CELERY_INTEGRATION.md](CELERY_INTEGRATION.md) for detailed documentation
2. Review [CELERY_QUICKSTART.md](CELERY_QUICKSTART.md) for usage examples
3. Check Celery worker console output for error messages
4. Check DeviceBackupResult.log for collection-specific errors
5. Check Redis logs: `redis-cli MONITOR` (careful, verbose!)
6. Enable Django DEBUG=True for more detailed error messages
