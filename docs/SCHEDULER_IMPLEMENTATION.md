# Backup Scheduler Implementation

## Overview

DeviceVault includes a comprehensive backup scheduler system that automatically triggers device backups based on configurable schedules (daily, weekly, monthly). The scheduler runs as a standalone daemon process with Redis-based distributed locking to ensure single-instance execution, and includes sophisticated missed-window detection for restart scenarios.

**Key Features:**
- Automated backup scheduling (daily, weekly, monthly)
- Single-instance guarantee via Redis distributed locking
- Missed-window detection with configurable restart window
- Timezone-aware scheduling (Australia/Sydney default)
- RBAC-filtered calendar visualization
- Real-time next backup display in device lists
- Seamless Celery integration for task distribution

## Architecture

### System Components

```
┌─────────────────────────────────────────────────────────────┐
│                    Scheduler Daemon                          │
│  (backups/scheduler.py - APScheduler based)                  │
│                                                              │
│  ┌────────────────┐  ┌──────────────────┐  ┌──────────┐   │
│  │ Redis Lock     │  │ Schedule Tick    │  │ Missed   │   │
│  │ Management     │  │ Processing       │  │ Window   │   │
│  │ (60s renewal)  │  │ (every minute)   │  │ Recovery │   │
│  └────────────────┘  └──────────────────┘  └──────────┘   │
└─────────────────┬────────────────────────────┬──────────────┘
                  │                            │
                  ▼                            ▼
          ┌───────────────┐          ┌─────────────────┐
          │  Redis Server │          │ Celery Workers  │
          │  (Locking)    │          │ (Task Queue)    │
          └───────────────┘          └─────────────────┘
                                              │
                  ┌───────────────────────────┘
                  ▼
          ┌────────────────┐
          │   PostgreSQL   │
          │   (State DB)   │
          └────────────────┘
                  ▲
                  │
          ┌───────┴────────────────────────────┐
          │                                    │
    ┌─────────────┐                   ┌───────────────┐
    │  Frontend   │                   │  REST API     │
    │  Calendar   │◄──────────────────│  (DRF)        │
    │  (Vue/Quasar)│                  │  /scheduled-  │
    └─────────────┘                   │  backups/     │
                                      └───────────────┘
```

### Process Flow

1. **Scheduler Daemon** starts and acquires Redis lock
2. Every minute, daemon checks all enabled schedules
3. For each schedule, evaluates if backup is due (timezone-aware)
4. Enqueues backup tasks via Celery to appropriate collection queues
5. Updates `last_run_at` and `next_run_at` in database
6. Frontend polls API for calendar data and device next-run times

## Database Models

### SchedulerState (core/models.py)

Singleton model tracking scheduler operational state:

```python
class SchedulerState(models.Model):
    last_tick = models.DateTimeField(null=True, blank=True)
    is_running = models.BooleanField(default=False)
    scheduler_pid = models.IntegerField(null=True, blank=True)
    last_restart_at = models.DateTimeField(null=True, blank=True)
    updated_at = models.DateTimeField(auto_now=True)
```

**Purpose:** Persist scheduler state for missed-window detection during restarts.

**Key Methods:**
- `load()` - Classmethod returning cached singleton instance
- `save()` - Forces pk=1 for singleton behavior

### BackupSchedule (policies/models.py)

Extended with execution tracking fields:

```python
class BackupSchedule(models.Model):
    # Existing fields: name, schedule_type, hour, minute, day_of_week, etc.
    last_run_at = models.DateTimeField(null=True, blank=True)  # NEW
    next_run_at = models.DateTimeField(null=True, blank=True)  # NEW
```

**Fields Added:**
- `last_run_at` - UTC timestamp of last execution
- `next_run_at` - UTC timestamp of next scheduled execution (cached)

### Device (devices/models.py)

Linked to schedules via foreign key:

```python
class Device(models.Model):
    # Existing fields...
    backup_schedule = models.ForeignKey(
        BackupSchedule,
        on_delete=models.SET_NULL,
        null=True,
        blank=True
    )  # NEW
```

**Behavior:** Nullable FK allows devices to opt-in to scheduling. When schedule deleted, FK set to NULL.

## Configuration

### backend/config/config.yaml

```yaml
scheduler:
  enabled: true
  restart_window_minutes: 120  # Missed-window catchup period
```

**Settings:**
- `enabled` - Enable/disable scheduler daemon
- `restart_window_minutes` - How far back to catch up missed backups on restart (default: 120 minutes / 2 hours)

### Environment Variables

- `DEVICEVAULT_CONFIG` - Path to config.yaml (default: `backend/config/config.yaml`)
- `REDIS_HOST` - Redis server hostname (default: `localhost`)
- `REDIS_PORT` - Redis server port (default: `6379`)
- `REDIS_DB` - Redis database number (default: `0`)

## Scheduler Daemon

### File: backend/backups/scheduler.py

**Execution:** `python -m backups.scheduler`

### Core Components

#### 1. Redis Distributed Locking

```python
def acquire_lock(self):
    """Acquire exclusive scheduler lock in Redis"""
    lock_acquired = self.redis_client.set(
        self.lock_key,
        self.instance_id,
        nx=True,  # Only set if not exists
        ex=self.lock_timeout  # Expire after timeout
    )
```

**Lock Properties:**
- Key: `devicevault:scheduler:lock`
- Timeout: 180 seconds (3 minutes)
- Renewed every 60 seconds during operation
- PID validation prevents stale lock issues

#### 2. Schedule Calculation

```python
def calculate_next_run(self, schedule, from_time=None):
    """Calculate next execution time in display timezone"""
    # Converts UTC to display timezone (Australia/Sydney)
    # Computes next occurrence based on schedule_type
    # Returns timezone-aware datetime in display timezone
```

**Schedule Types:**
- **Daily:** Next occurrence of hour:minute
- **Weekly:** Next occurrence of day_of_week at hour:minute
- **Monthly:** Next occurrence of day_of_month at hour:minute

**Timezone Handling:**
- All DB times stored in UTC
- Schedule calculations in `DEVICEVAULT_DISPLAY_TIMEZONE`
- Uses `utc_to_local()` and `local_to_utc()` from `core.timezone_utils`

#### 3. Missed Window Detection

```python
def process_missed_backups(self, scheduler_state):
    """On startup, handle backups missed during downtime"""
    # Compare last_tick to current time
    # Iterate potential executions
    # Enqueue if within restart_window_minutes
    # Create 'missed_window' result if too old
```

**Behavior:**
- Runs once on daemon startup
- Only processes schedules with `last_tick` set
- Missed executions within restart window: **enqueued for execution**
- Missed executions outside restart window: **marked as 'missed_window' in DeviceBackupResult**

#### 4. Task Enqueueing

```python
def enqueue_device_backup(self, device, schedule, is_catchup=False):
    """Send backup task to Celery queue"""
    queue = collection_queue_name_from_group(device.collection_group)
    celery_app.send_task(
        'device.collect',
        args=[json.dumps(backup_config)],
        queue=queue
    )
```

**Queue Routing:** Uses device's `collection_group` to determine Celery queue, ensuring serial processing per group.

### Signal Handlers

#### backend/backups/signals.py

```python
@receiver(post_save, sender=BackupSchedule)
def update_schedule_next_run(sender, instance, created, **kwargs):
    """Recalculate next_run_at when schedule modified"""
    next_run_utc = calculate_next_run(instance)
    BackupSchedule.objects.filter(pk=instance.pk).update(
        next_run_at=next_run_utc
    )
```

**Purpose:** Invalidate cached `next_run_at` when schedule configuration changes.

## API Endpoints

### GET /api/scheduled-backups/calendar/

**File:** backend/api/views.py - `ScheduledBackupsCalendarView`

**Purpose:** Returns 30-day calendar of scheduled backups with RBAC filtering.

**Response Format:**
```json
{
  "2026-01-15": [
    {
      "schedule_id": 1,
      "schedule_name": "Daily 2 AM",
      "time": "02:00",
      "device_count": 5,
      "devices": [
        {"id": 1, "name": "Core-Router-01", "ip_address": "192.168.1.1"},
        {"id": 2, "name": "Access-Switch-02", "ip_address": "192.168.1.2"}
      ]
    }
  ],
  "2026-01-16": [...]
}
```

**RBAC Filtering:**
- Uses `user_get_accessible_device_groups()` to filter devices
- Users see all schedules but only devices they have access to
- Device list may be empty if user has no permissions for that schedule's devices

**Calendar Window:** Today to Today+30 days

### Device Serializer Updates

**File:** backend/api/serializers.py

```python
class DeviceSerializer(serializers.ModelSerializer):
    backup_schedule = BackupScheduleSerializer(read_only=True)
    
    class Meta:
        fields = [..., 'backup_schedule']
```

**Impact:** Device list API now includes nested schedule data with `next_run_at` field.

## Frontend Components

### 1. Schedule Calendar Page

**File:** frontend/src/pages/ScheduleCalendar.vue

**Route:** `/vaultadmin/schedule-calendar`

**Features:**
- Monthly calendar grid view
- Month navigation (previous/next)
- Schedule badges showing device count per schedule
- Hover tooltips with device list
- Auto-refresh every 5 minutes
- Filtered by user's RBAC permissions

**UI Elements:**
- Header: Month/Year display with navigation buttons
- Table: Rows grouped by date
- Badges: Color-coded per schedule with device count
- Tooltips: Device names on hover

### 2. Devices Page Enhancement

**File:** frontend/src/pages/Devices.vue

**New Column:** "Next Scheduled Backup"

**Display Logic:**
```javascript
formatNextScheduledBackup(schedule) {
  if (!schedule || !schedule.next_run_at) return 'Not scheduled';
  
  const nextRun = new Date(schedule.next_run_at);
  const now = new Date();
  const diffMs = nextRun - now;
  
  // Returns: "Tomorrow at 14:00", "In 3 hours", "Not scheduled"
}
```

**Tooltip:** Shows schedule name on hover

### 3. Edit Device Form

**File:** frontend/src/pages/EditDevice.vue

**New Field:** Backup Schedule dropdown selector

**Features:**
- Loads available schedules from `/api/backup-schedules/`
- Clearable dropdown (can unassign schedule)
- Saves schedule assignment on device update

## Deployment

### Standalone Script

**File:** start-scheduler.sh (repository root)

```bash
#!/bin/bash
cd backend
source ../.venv/bin/activate
export DEVICEVAULT_CONFIG="${DEVICEVAULT_CONFIG:-config/config.yaml}"
exec python -m backups.scheduler
```

**Usage:**
```bash
./start-scheduler.sh
```

### Integration with devicevault.sh

**Added Functions:**
- `start_scheduler()` - Starts scheduler daemon in background
- `stop_scheduler()` - Stops scheduler daemon gracefully

**Usage:**
```bash
./devicevault.sh start   # Starts frontend + backend + scheduler
./devicevault.sh stop    # Stops all services including scheduler
```

**PID Tracking:** Uses `SCHEDULER_PID_FILE=/tmp/devicevault-scheduler.pid`

### Docker Compose

**File:** docker-build/docker-compose.yaml

```yaml
services:
  scheduler:
    build:
      context: ../backend
      dockerfile: ../docker-build/Dockerfile.django
    command: python -m backups.scheduler
    env_file:
      - ./config/django.env
    depends_on:
      - django
      - postgres
      - redis
    restart: unless-stopped
```

**Usage:**
```bash
cd docker-build
make up          # Starts all services including scheduler
docker compose logs scheduler  # View scheduler logs
```

## Migrations

**Generated Migrations:**
1. `core/migrations/0008_schedulerstate_*` - SchedulerState model
2. `policies/migrations/0003_backupschedule_*` - last_run_at, next_run_at fields
3. `devices/migrations/0018_device_backup_schedule` - backup_schedule FK
4. Additional ID field migrations for audit, credentials, locations

**Apply Migrations:**
```bash
cd backend
source ../.venv/bin/activate
python manage.py migrate
```

## Usage Guide

### Creating a Backup Schedule

1. Navigate to **Admin → Backup Schedules**
2. Click **Create New Schedule**
3. Configure:
   - Name (e.g., "Daily 2 AM")
   - Schedule Type: Daily/Weekly/Monthly
   - Hour and Minute (in display timezone)
   - Day of week (weekly) or Day of month (monthly)
4. Save schedule

### Assigning Devices to Schedule

**Method 1: Edit Device Form**
1. Navigate to **Devices → [Device Name]**
2. Click **Edit**
3. Select schedule from **Backup Schedule** dropdown
4. Save device

**Method 2: Bulk Assignment (future enhancement)**
- Not yet implemented

### Viewing Scheduled Backups

**Calendar View:**
1. Navigate to **Admin → Schedule Calendar**
2. View upcoming backups for next 30 days
3. Hover over schedule badges to see device list
4. Navigate between months using arrow buttons

**Device List View:**
1. Navigate to **Devices**
2. View **Next Scheduled Backup** column
3. Hover to see schedule name

### Monitoring Scheduler

**Check Scheduler Status:**
```bash
# Standalone
ps aux | grep scheduler.py

# Docker
docker compose ps scheduler
docker compose logs -f scheduler
```

**Verify Lock in Redis:**
```bash
redis-cli GET devicevault:scheduler:lock
```

**Check SchedulerState:**
```bash
cd backend
python manage.py shell
>>> from core.models import SchedulerState
>>> state = SchedulerState.load()
>>> print(f"Running: {state.is_running}, PID: {state.scheduler_pid}")
>>> print(f"Last tick: {state.last_tick}")
```

## Troubleshooting

### Scheduler Won't Start

**Symptom:** Scheduler exits immediately

**Checks:**
1. Verify Redis is running: `redis-cli ping`
2. Check config.yaml: `scheduler.enabled: true`
3. Check Django migrations applied: `python manage.py migrate`
4. Review logs for ImportError or configuration issues

**Solution:**
```bash
cd backend
python -m backups.scheduler  # Run in foreground to see errors
```

### Missed Backups After Restart

**Symptom:** Backups marked as 'missed_window' instead of executing

**Cause:** Downtime exceeded `restart_window_minutes` (default: 120)

**Solution:**
- Increase `restart_window_minutes` in config.yaml
- Or accept missed windows and rely on next scheduled execution

**Verify:**
```bash
cd backend
python manage.py shell
>>> from devices.models import DeviceBackupResult
>>> DeviceBackupResult.objects.filter(status='missed_window').count()
```

### Multiple Scheduler Instances

**Symptom:** Duplicate backup tasks enqueued

**Cause:** Redis locking failed or multiple hosts running scheduler

**Check:**
```bash
redis-cli GET devicevault:scheduler:lock
redis-cli TTL devicevault:scheduler:lock  # Should show ~180 seconds
```

**Solution:**
- Ensure only one scheduler daemon running
- Verify Redis connectivity from scheduler host
- Check scheduler logs for lock acquisition failures

### Timezone Issues

**Symptom:** Backups running at wrong times

**Cause:** Mismatch between display timezone and schedule configuration

**Check:**
```bash
cd backend
python manage.py shell
>>> from core.timezone_utils import get_display_timezone
>>> print(get_display_timezone())  # Should show Australia/Sydney
```

**Solution:**
- Verify `DEVICEVAULT_DISPLAY_TIMEZONE` in config.yaml
- Ensure schedule hour/minute configured in display timezone
- Check Django `USE_TZ=True` and `TIME_ZONE='UTC'` in settings

### Device Not Backing Up

**Symptom:** Device assigned to schedule but no backups triggered

**Checks:**
1. Device enabled: `device.enabled = True`
2. Schedule enabled: `schedule.enabled = True`
3. Device has backup_schedule FK set
4. Scheduler daemon running
5. Next_run_at is in future

**Debug:**
```bash
cd backend
python manage.py shell
>>> from devices.models import Device
>>> device = Device.objects.get(name='Core-Router-01')
>>> print(f"Schedule: {device.backup_schedule}")
>>> print(f"Next run: {device.backup_schedule.next_run_at}")
```

### Signal Handler Not Updating next_run_at

**Symptom:** Editing schedule doesn't update next_run_at

**Cause:** Signal not registered or exception in signal handler

**Check:**
```bash
cd backend
python manage.py shell
>>> from policies.models import BackupSchedule
>>> schedule = BackupSchedule.objects.first()
>>> schedule.hour = 15
>>> schedule.save()
>>> schedule.refresh_from_db()
>>> print(schedule.next_run_at)  # Should be updated
```

**Solution:**
- Verify `backups/apps.py` has `def ready(self): from . import signals`
- Check logs for exceptions in signal handler
- Manually recalculate: `python manage.py shell` then run calculate_next_run()

## Technical Notes

### Hybrid Caching Strategy

**On-the-fly calculation:** Scheduler daemon always calls `calculate_next_run()` during tick processing for authoritative execution decisions.

**Cached next_run_at:** Stored in database for API/frontend display performance. Updated by:
1. Scheduler daemon after each execution
2. Signal handler when schedule modified

**Rationale:** Execution decisions require real-time accuracy; frontend display can tolerate brief cache staleness.

### Lock Renewal Pattern

**Acquisition:** 180-second expiry on initial lock acquisition

**Renewal:** Every 60 seconds during `process_schedules()` tick

**Failure Handling:** If renewal fails, daemon releases lock and exits gracefully

**Benefit:** Prevents stale locks from blocking scheduler restart after crashes

### Missed Window Logic

**Restart Window:** Configurable period (default 2 hours) for catching up missed executions

**Within Window:** Backup task enqueued normally with `is_catchup=True` flag

**Outside Window:** DeviceBackupResult created with `status='missed_window'` for audit trail

**Edge Case:** If multiple executions missed, each one processed independently

### Queue Routing

**Collection Groups:** Devices belong to collection groups for serial processing

**Queue Selection:** `collection_queue_name_from_group()` maps group to Celery queue

**Benefit:** Prevents concurrent backups to same device or vendor API

## Future Enhancements

### Planned Features

1. **Bulk Schedule Assignment** - Assign multiple devices to schedule from device list
2. **Schedule Templates** - Pre-configured schedules for common patterns
3. **Execution History** - Calendar view of past executions with success/failure indicators
4. **Schedule Analytics** - Success rate, average duration, failure patterns
5. **Cron Expression Support** - Advanced scheduling via cron syntax
6. **Schedule Priorities** - Control execution order when multiple schedules due
7. **Maintenance Windows** - Blackout periods when backups should not run
8. **Email Notifications** - Alert on missed windows or schedule failures

### API Enhancements

1. **POST /api/scheduled-backups/bulk-assign/** - Assign devices to schedules in bulk
2. **GET /api/scheduled-backups/history/** - Historical execution data
3. **POST /api/scheduled-backups/{id}/test/** - Trigger immediate test execution

## Related Documentation

- [BACKUP_METHODS_IMPLEMENTATION.md](BACKUP_METHODS_IMPLEMENTATION.md) - How backups are collected
- [CELERY_INTEGRATION.md](CELERY_INTEGRATION.md) - Task queue architecture
- [TIMEZONE_IMPLEMENTATION.md](TIMEZONE_IMPLEMENTATION.md) - Timezone handling
- [RBAC_REORGANIZATION_COMPLETE.md](RBAC_REORGANIZATION_COMPLETE.md) - Permission system

## References

**Key Files:**
## Graceful Shutdown & Recovery

### Lock Management

The scheduler uses Redis distributed locking to prevent multiple instances from running simultaneously. The lock mechanism includes sophisticated recovery for crash scenarios:

**Lock Properties:**
- Key: `devicevault:scheduler:lock`
- TTL: 180 seconds (3 minutes) - auto-expires if not renewed
- Renewal: Every 60 seconds during normal operation
- Value: Current process PID for validation

### Graceful Shutdown Process

1. **Signal Reception** - SIGTERM or SIGINT received
2. **Graceful Drain** - Current tick completes, no new backups enqueued
3. **State Cleanup** - SchedulerState marked as `is_running=False`
4. **Lock Release** - Redis lock explicitly deleted
5. **Exit** - Process terminates

**Signal Handling:**
```python
# Handler registered for both SIGTERM and SIGINT
def shutdown_handler(signum, frame):
    global shutdown_requested
    logger.info(f"Received signal {signum}, initiating graceful shutdown...")
    shutdown_requested = True
```

### Stale Lock Detection & Recovery

If scheduler crashes without releasing lock, automatic recovery mechanisms prevent manual intervention:

#### Method 1: Automatic on Startup
```bash
# Checks if lock-holding PID still exists
# If process is dead, clears stale lock
./start-scheduler.sh
```

#### Method 2: Manual Commands
```bash
# Check current lock status (alive/dead/none)
./start-scheduler.sh --check-lock

# Force clear stale lock (use if crash detected)
./start-scheduler.sh --clear-lock
```

#### Method 3: Direct Python
```bash
cd backend
python -m backups.scheduler --check-lock   # View lock status
python -m backups.scheduler --clear-lock   # Clear stale lock
```

**Example Output:**
```
# Lock held by live process
🔒 Lock held by PID 12345 (process is alive)

# Stale lock from dead process
⚠️  Lock held by dead PID 12345 (stale lock)

# No lock
🔓 No scheduler lock held
```

### Automatic Cleanup on Restart

The devicevault.sh script automatically clears stale locks before restarting:

```bash
./devicevault.sh restart   # Automatically clears stale locks
```

**Behind the scenes:**
1. Calls `start-scheduler.sh --clear-lock` (safe operation)
2. Waits for scheduler to acquire new lock
3. Resumes normal operation

### Lock Acquisition Flow

```
Startup Attempt
      │
      ├─→ Check for stale lock (is PID alive?)
      │    Yes: Release stale lock
      │    No: Lock already released
      │
      ├─→ Attempt to acquire lock (SET nx=True, ex=180)
      │    Success: Start scheduler loop
      │    Failure: Another instance running (exit)
      │
      └─→ Every 60s: Renew lock (extend TTL)
           If renewal fails: Lost lock → Exit gracefully
```

### Troubleshooting Lock Issues

**Symptom:** "Failed to acquire lock, another instance may be running"

**Diagnosis:**
```bash
./start-scheduler.sh --check-lock
```

**Solutions:**
- **If lock is held by live PID:** Stop that scheduler instance and restart
  ```bash
  kill -TERM <PID>  # Graceful shutdown
  ./devicevault.sh start  # Restart
  ```

- **If lock is held by dead PID:** Force clear it
  ```bash
  ./start-scheduler.sh --clear-lock
  ./devicevault.sh start  # Restart
  ```

- **If Redis is unavailable:** Check Redis connectivity
  ```bash
  redis-cli ping  # Should return PONG
  ```

### Recovery Scenarios

**Scenario 1: Scheduler Crash**
1. Process exits with Redis lock still held
2. Lock TTL countdown starts (180 seconds)
3. Option A (manual): Run `--clear-lock` to instant recovery
4. Option B (auto): Wait 3 minutes, lock auto-expires, restart acquires it

**Scenario 2: Restart During Active Backups**
1. SIGTERM sent to scheduler
2. Current tick completes gracefully
3. No new backups enqueued mid-operation
4. Lock released cleanly
5. Restart acquires lock, processes missed backups if needed

**Scenario 3: Redis Unavailable During Shutdown**
1. Lock release fails (Redis down)
2. Process still exits gracefully
3. Lock will auto-expire after 180 seconds
4. When Redis restored, stale lock detected and cleared on next startup

### Best Practices

1. **Always use SIGTERM for shutdown** - Allows graceful lock release
   ```bash
   kill -TERM <PID>  # Graceful (recommended)
   kill -9 <PID>     # Force (causes stale lock)
   ```

2. **Monitor restart logs** for lock acquisition
   ```bash
   tail -f /tmp/devicevault/scheduler.log
   ```

3. **Check lock status after crash**
   ```bash
   ./start-scheduler.sh --check-lock
   ```

4. **Use devicevault.sh for management** - Handles locks automatically
   ```bash
   ./devicevault.sh start/stop/restart
   ```

5. **Set reasonable restart_window_minutes** - Prevents excessive catch-up
   ```yaml
   # backend/config/config.yaml
   scheduler:
     enabled: true
     restart_window_minutes: 120  # 2 hours
   ```

- Backend: [backend/backups/scheduler.py](../backend/backups/scheduler.py)
- Signals: [backend/backups/signals.py](../backend/backups/signals.py)
- Models: [backend/core/models.py](../backend/core/models.py), [backend/policies/models.py](../backend/policies/models.py), [backend/devices/models.py](../backend/devices/models.py)
- API: [backend/api/views.py](../backend/api/views.py)
- Frontend Calendar: [frontend/src/pages/ScheduleCalendar.vue](../frontend/src/pages/ScheduleCalendar.vue)
- Config: [backend/config/config.yaml](../backend/config/config.yaml)
- Startup: [start-scheduler.sh](../start-scheduler.sh), [devicevault.sh](../devicevault.sh)
- Docker: [docker-build/docker-compose.yaml](../docker-build/docker-compose.yaml)

**Implementation Date:** January 2026

**Contributors:** DeviceVault Development Team
