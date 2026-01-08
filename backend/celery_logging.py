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

"""
Structured JSON logging configuration for DeviceVault Celery workers and tasks.

Celery tasks use python-json-logger to emit structured JSON logs that include:
- task_id: Celery task UUID
- device_id: Device being processed
- operation: High-level operation name (lock, plugin, storage, result)
- status: Operation success/failure
- duration_ms: Time spent on operation
- error: Error message if failed

Example log output:
{
  "timestamp": "2026-01-08T10:15:30.123Z",
  "level": "INFO",
  "logger": "celery_app",
  "task_id": "abc123def456",
  "device_id": 42,
  "operation": "plugin_execution",
  "status": "success",
  "duration_ms": 1250,
  "message": "Mikrotik export completed"
}

This enables:
- Centralized log aggregation (ELK, Datadog, etc.)
- Structured filtering: logs | select .task_id == "xyz"
- Performance monitoring: track duration_ms across operations
- Error tracking: filter by status == "failure"
- Distributed tracing: correlate logs by task_id and device_id
"""

import logging
import json
from datetime import datetime
from pythonjsonlogger import jsonlogger


class DeviceVaultJSONFormatter(jsonlogger.JsonFormatter):
    """
    Custom JSON formatter that adds DeviceVault-specific context.
    
    Adds structured fields:
    - timestamp: ISO 8601 UTC timestamp
    - service: Always "devicevault-worker" for filtering
    - environment: From DEVICEVAULT_ENV variable (dev/prod)
    """
    
    def add_fields(self, log_record, record, message_dict):
        super(DeviceVaultJSONFormatter, self).add_fields(
            log_record, record, message_dict
        )
        
        # Add custom fields
        log_record['timestamp'] = datetime.utcnow().isoformat() + 'Z'
        log_record['service'] = 'devicevault-worker'
        log_record['level'] = record.levelname
        log_record['logger'] = record.name


def configure_structured_logging(logger_name='devicevault'):
    """
    Configure structured JSON logging for Celery workers.
    
    Sets up JSON formatter for console output and optional file output.
    
    Usage:
        # In celery_app.py or worker startup
        configure_structured_logging('celery_app')
    
    Output:
        All log messages are emitted as JSON to stdout/stderr with full context.
    """
    import os
    
    logger = logging.getLogger(logger_name)
    logger.setLevel(logging.DEBUG)
    
    # Console handler with JSON formatting
    console_handler = logging.StreamHandler()
    console_handler.setLevel(logging.DEBUG)
    
    formatter = DeviceVaultJSONFormatter(
        '%(timestamp)s %(level)s %(name)s %(message)s'
    )
    console_handler.setFormatter(formatter)
    logger.addHandler(console_handler)
    
    # Optional: File handler for persistent logs
    log_file = os.environ.get('DEVICEVAULT_LOG_FILE')
    if log_file:
        file_handler = logging.FileHandler(log_file)
        file_handler.setLevel(logging.DEBUG)
        file_handler.setFormatter(formatter)
        logger.addHandler(file_handler)
    
    return logger


# Example structured logging statements for task operations
# (Include in documentation for development reference)

EXAMPLE_LOGS = """
# Example 1: Successful lock acquisition
{
  "timestamp": "2026-01-08T10:15:30.123Z",
  "level": "INFO",
  "logger": "celery_app.locks",
  "task_id": "abc123",
  "device_id": 5,
  "operation": "lock_acquire",
  "status": "success",
  "lock_key": "lock:device:5",
  "duration_ms": 5,
  "message": "Lock acquired for device 5"
}

# Example 2: Lock contention
{
  "timestamp": "2026-01-08T10:15:31.456Z",
  "level": "WARNING",
  "logger": "celery_app.locks",
  "task_id": "def456",
  "device_id": 5,
  "operation": "lock_acquire",
  "status": "failure",
  "lock_key": "lock:device:5",
  "held_by": "2026-01-08T10:14:30.000Z",
  "duration_ms": 2,
  "message": "Lock contention for device 5: held by another task"
}

# Example 3: Plugin execution success
{
  "timestamp": "2026-01-08T10:15:35.789Z",
  "level": "INFO",
  "logger": "celery_app.plugin",
  "task_id": "abc123",
  "device_id": 5,
  "plugin_key": "mikrotik_ssh_export",
  "operation": "plugin_execution",
  "status": "success",
  "config_size_bytes": 4096,
  "duration_ms": 2500,
  "message": "Plugin execution completed successfully"
}

# Example 4: Plugin timeout
{
  "timestamp": "2026-01-08T10:15:40.000Z",
  "level": "ERROR",
  "logger": "celery_app.plugin",
  "task_id": "abc123",
  "device_id": 5,
  "plugin_key": "mikrotik_ssh_export",
  "operation": "plugin_execution",
  "status": "failure",
  "error_type": "CollectorTimeoutException",
  "error_message": "SSH connection to 192.168.1.1 timed out after 30s",
  "duration_ms": 30000,
  "message": "Plugin execution timeout"
}

# Example 5: Storage save
{
  "timestamp": "2026-01-08T10:15:42.123Z",
  "level": "INFO",
  "logger": "celery_app.storage",
  "task_id": "abc123",
  "device_id": 5,
  "operation": "storage_save",
  "status": "success",
  "storage_type": "filesystem",
  "artifact_path": "backups/router-1/mikrotik_ssh_export/Router/5.cfg",
  "size_bytes": 4096,
  "duration_ms": 150,
  "message": "Device configuration saved to storage"
}

# Example 6: Result record creation
{
  "timestamp": "2026-01-08T10:15:43.456Z",
  "level": "INFO",
  "logger": "celery_app.result",
  "task_id": "abc123",
  "device_id": 5,
  "operation": "result_create",
  "status": "success",
  "task_identifier": "5:abc123",
  "duration_ms": 50,
  "message": "DeviceBackupResult record created"
}

# Flower debugging instructions:
# Launch Flower web UI for task monitoring:
#   celery -A devicevault flower --port=5555
# Access at: http://localhost:5555/
# Features:
#   - Real-time task execution monitoring
#   - Worker pool statistics
#   - Task history and results
#   - Rate limiting and task filtering
# NOTE: Flower is for development/debugging only. Do not expose to production networks.
"""
