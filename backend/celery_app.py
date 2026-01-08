"""
DeviceVault - A comprehensive network device backup management application with web interface for user and admin access and backend component for automated backup collection.
Copyright (C) 2026, Slinky Software

This program is free software: you can redistribute it and/or modify
it under the terms of the GNU General Public License as published by
the Free Software Foundation, either version 3 of the License, or
(at your option) any later version.

This program is distributed in the hope that it will be useful,
but WITHOUT ANY WARRANTY; without even the implied warranty of
MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
GNU General Public License for more details.

You should have received a copy of the GNU General Public License
along with this program.  If not, see <http://www.gnu.org/licenses/>.
"""

import os
import logging
from celery import Celery, current_task
from celery.signals import task_prerun, task_postrun, task_failure
from django.conf import settings

# Set Django settings module
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'devicevault.settings')

# Create Celery app instance
app = Celery('devicevault')

# Configure from Django settings with custom prefix
app.config_from_object('django.conf:settings', namespace='CELERY')

# Auto-discover tasks from all registered Django apps
app.autodiscover_tasks()

logger = logging.getLogger(__name__)


def get_queue_for_collection_group(collection_group_name=None):
    """
    Determine the queue name based on collection group.
    
    Routing rules:
    - If collection_group is defined: route to "collector.group.<group_name>"
    - If None: route to "default" (any available worker node)
    
    Args:
        collection_group_name: Name of the collection group or None
    
    Returns:
        Queue name string
    """
    if collection_group_name:
        return f"collector.group.{collection_group_name}"
    return "collector.default"


@app.task(bind=True, name='device.collect', 
          autoretry_for=(Exception,), 
          retry_kwargs={'max_retries': 3, 'countdown': 60},
          acks_late=True, reject_on_worker_lost=True)
def device_collect_task(self, device_id: int, config_json: str, collection_group: str = None):
    """
    Celery task for collecting device backup.
    
    This task:
    1. Acquires a per-device Redis lock to prevent concurrent collection
    2. Validates device configuration
    3. Invokes the appropriate backup plugin with timeout handling
    4. Stores the device configuration externally (filesystem or cloud)
    5. Creates a DeviceBackupResult record with task_identifier for later retrieval
    
    Args:
        device_id: Database ID of device to backup
        config_json: JSON string containing collection config with ip, username, password, etc.
        collection_group: Optional collection group name for routing context
    
    Returns:
        Dict with keys: task_id, status, timestamp, log, device_config_ref, task_identifier
    
    Raises:
        Retries on transient failures (network, auth timeouts)
        Returns structured failure dict on plugin/validation errors
    
    Queue routing:
        - If collection_group provided: "collector.group.<group_name>"
        - Otherwise: "collector.default"
    """
    import json
    import hashlib
    from datetime import datetime
    from django.utils import timezone
    from devices.models import Device
    from backups.plugins import get_plugin
    from storage.fs import FileSystemStorage
    from devices.models import DeviceBackupResult
    
    task_id = self.request.id
    log_messages = []
    start_time = datetime.utcnow()
    
    try:
        # ===== Step 1: Lock Acquisition =====
        lock_acquired, lock_key = acquire_device_lock(device_id, timeout=3600)
        if not lock_acquired:
            log_messages.append(f"Failed to acquire lock for device {device_id} - another collection in progress")
            return {
                "task_id": task_id,
                "status": "failure",
                "timestamp": datetime.utcnow().isoformat() + "Z",
                "log": log_messages,
                "device_config_ref": None,
                "task_identifier": None
            }
        
        log_messages.append(f"[Lock] Acquired lock for device {device_id}")
        
        try:
            # ===== Step 2: Device & Plugin Validation =====
            device = Device.objects.get(id=device_id)
            log_messages.append(f"[Device] Loaded device: {device.name} ({device.ip_address})")
            
            plugin = get_plugin(device.backup_method)
            if not plugin:
                raise ValueError(f"Unknown backup method for device {device.name}: {device.backup_method}")
            
            log_messages.append(f"[Plugin] Using backup method: {plugin.key}")
            
            # ===== Step 3: Plugin Execution =====
            config = json.loads(config_json)
            log_messages.append(f"[Config] Collection config loaded")
            
            # Invoke plugin with async interface
            result = plugin.collect_async(config, timeout=config.get('timeout', 30), task_id=task_id)
            log_messages.extend(result.get('log', []))
            
            if result['status'] == 'failure':
                # Plugin failed - return structured failure
                task_identifier = generate_task_identifier(device_id, task_id)
                return {
                    "task_id": task_id,
                    "status": "failure",
                    "timestamp": result.get('timestamp', datetime.utcnow().isoformat() + "Z"),
                    "log": log_messages,
                    "device_config_ref": None,
                    "task_identifier": task_identifier
                }
            
            # ===== Step 4: External Storage =====
            device_config = result.pop('_raw_device_config', '')
            if device_config:
                storage = FileSystemStorage(base_path=os.environ.get('DEVICEVAULT_BACKUPS', 'backups'))
                rel_path = f"{device.name}/{device.backup_method}/{device.device_type.name}/{device.id}.cfg"
                device_config_ref = storage.save(rel_path, device_config)
                log_messages.append(f"[Storage] Device config saved to {device_config_ref}")
                result['device_config_ref'] = device_config_ref
            
            # ===== Step 5: ORM Result Record =====
            task_identifier = generate_task_identifier(device_id, task_id)
            log_json = json.dumps(log_messages)
            
            DeviceBackupResult.objects.create(
                task_id=task_id,
                task_identifier=task_identifier,
                device=device,
                status=result['status'],
                timestamp=timezone.now(),
                log=log_json
            )
            
            log_messages.append(f"[Result] Created DeviceBackupResult record with task_identifier {task_identifier}")
            
            # Update device last backup time
            device.last_backup_time = timezone.now()
            device.last_backup_status = 'success'
            device.save(update_fields=['last_backup_time', 'last_backup_status'])
            
            return {
                "task_id": task_id,
                "status": result['status'],
                "timestamp": result.get('timestamp', datetime.utcnow().isoformat() + "Z"),
                "log": log_messages,
                "device_config_ref": result.get('device_config_ref'),
                "task_identifier": task_identifier
            }
        
        finally:
            # Always release lock
            release_device_lock(lock_key)
            log_messages.append(f"[Lock] Released lock for device {device_id}")
    
    except Exception as e:
        # Unhandled exception - log and return structured failure
        log_messages.append(f"[Error] Unexpected error: {str(e)}")
        import traceback
        log_messages.append(f"[Traceback] {traceback.format_exc()}")
        
        return {
            "task_id": task_id,
            "status": "failure",
            "timestamp": datetime.utcnow().isoformat() + "Z",
            "log": log_messages,
            "device_config_ref": None,
            "task_identifier": None
        }


@app.task(name='device.collect.stale', autoretry_for=(Exception,), retry_kwargs={'max_retries': 2})
def device_collect_stale_task(device_id: int):
    """
    Simulated stale/overrun task for testing lock contention.
    
    This task:
    1. Acquires lock for device
    2. Sleeps to simulate long-running collection
    3. Then releases lock
    
    Used to demonstrate lock contention and how new collect attempts
    will fail gracefully when a stale task holds the lock.
    """
    import time
    from django.utils import timezone
    from devices.models import Device
    
    task_id = current_task.request.id
    log_messages = []
    
    try:
        lock_acquired, lock_key = acquire_device_lock(device_id, timeout=120)
        if not lock_acquired:
            return {
                "task_id": task_id,
                "status": "failure",
                "log": [f"Could not acquire lock for device {device_id} - stale task simulation failed"],
                "reason": "lock_contention"
            }
        
        log_messages.append(f"Stale task acquired lock, sleeping 60 seconds...")
        time.sleep(60)  # Simulate stuck task
        log_messages.append("Stale task complete")
        
        return {
            "task_id": task_id,
            "status": "success",
            "log": log_messages
        }
    
    finally:
        try:
            release_device_lock(lock_key)
        except:
            pass


def acquire_device_lock(device_id: int, timeout: int = 3600) -> tuple:
    """
    Acquire a Redis lock for a device to ensure only one collection at a time.
    
    Args:
        device_id: Device database ID
        timeout: Lock timeout in seconds (default 1 hour)
    
    Returns:
        Tuple of (lock_acquired: bool, lock_key: str)
        - lock_acquired: True if lock was acquired, False if already held
        - lock_key: Redis key name for later release
    
    Implementation:
        Uses redis-py SET with NX (only if not exists) to atomically acquire.
        Lock value is a timestamp for debugging which process holds it.
    """
    import redis
    from datetime import datetime
    
    lock_key = f"lock:device:{device_id}"
    lock_value = datetime.utcnow().isoformat()
    
    try:
        # Redis is typically accessed via CELERY_BROKER_URL
        # For development, if not available, return True to allow execution
        redis_client = redis.from_url(
            os.environ.get('CELERY_BROKER_URL', 'redis://localhost:6379/0')
        )
        
        # SET lock_key lock_value NX EX timeout
        # Returns True if set, None if already exists
        acquired = redis_client.set(lock_key, lock_value, nx=True, ex=timeout)
        
        if acquired:
            logger.info(f"Lock acquired for device {device_id}: {lock_key}")
            return (True, lock_key)
        else:
            existing_value = redis_client.get(lock_key)
            logger.warning(f"Lock contention for device {device_id}: held by {existing_value}")
            return (False, lock_key)
    
    except redis.ConnectionError:
        # Redis unavailable - log warning and allow execution
        # In production, you might want stricter locking via database locks
        logger.warning(f"Redis unavailable for lock on device {device_id}, allowing execution")
        return (True, None)


def release_device_lock(lock_key: str):
    """
    Release a Redis lock by key name.
    
    Args:
        lock_key: Redis key from acquire_device_lock
    
    Implementation:
        Deletes the key. If Redis is unavailable, logs warning.
    """
    if not lock_key:
        return
    
    import redis
    
    try:
        redis_client = redis.from_url(
            os.environ.get('CELERY_BROKER_URL', 'redis://localhost:6379/0')
        )
        redis_client.delete(lock_key)
        logger.info(f"Lock released: {lock_key}")
    except redis.ConnectionError:
        logger.warning(f"Redis unavailable to release lock {lock_key}")


def generate_task_identifier(device_id: int, task_id: str) -> str:
    """
    Generate a stable task_identifier for external storage reference.
    
    The task_identifier is used to retrieve device_config from external storage
    without storing it in the ORM. It's a combination of device ID and task ID.
    
    Args:
        device_id: Database device ID
        task_id: Celery task ID
    
    Returns:
        Task identifier string suitable as storage key/path component
    """
    import hashlib
    
    # Create stable identifier: device_id:task_id
    # Can also add timestamp for uniqueness per collection cycle
    identifier = f"{device_id}:{task_id}"
    return identifier


@app.task(name='scheduling.list_pending')
def list_pending_collections():
    """
    List all devices pending collection (for Beat scheduler or manual invocation).
    
    Returns:
        List of device IDs that are enabled and not example data
    """
    from devices.models import Device
    
    devices = Device.objects.filter(
        enabled=True,
        is_example_data=False
    ).values_list('id', flat=True)
    
    return list(devices)
