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

import json
import time
from datetime import datetime

from celery.exceptions import SoftTimeLimitExceeded

from devicevault_protocol.names import COLLECT_RESULTS_STREAM, COLLECT_TASK, device_lock_key
from devicevault_worker.app import app, get_logger, redis_client
from devicevault_worker.plugins import get_plugin

logger = get_logger('devicevault.worker')


@app.task(
    bind=True,
    name=COLLECT_TASK,
    soft_time_limit=300,
    time_limit=350,
    acks_late=True,
    autoretry_for=(Exception,),
    retry_backoff=True,
    retry_kwargs={'max_retries': 3},
)
def device_collect_task(self, config_json: str) -> dict:
    """Collect device configuration using the configured backup plugin.

    Args:
        config_json: JSON string of a dict containing at minimum:
            - device_id: optional device PK (integer)
            - task_identifier: logical identifier for this job
            - ip: device IP
            - credentials: dict
            - backup_method: plugin key
            - timeout: optional task timeout seconds

    Returns:
        dict matching collector result schema. This function also persists a DeviceBackupResult row.
    """
    try:
        cfg = json.loads(config_json)
    except Exception as exc:
        logger.exception('invalid_config_json')
        return {
            'task_id': None,
            'status': 'failure',
            'timestamp': datetime.utcnow().isoformat() + 'Z',
            'log': [f'invalid_config_json: {repr(exc)}'],
            'device_config': None,
        }

    device_id = cfg.get('device_id')
    task_identifier = cfg.get('task_identifier') or f'collect:{device_id}:{datetime.utcnow().isoformat()}'
    timeout = cfg.get('timeout', 240)

    lock_key = device_lock_key(device_id) if device_id else None
    lock = None
    lock_acquired = False

    if lock_key:
        lock = redis_client.lock(lock_key, timeout=timeout + 60, blocking=False)
        try:
            lock_acquired = lock.acquire(blocking=False)
        except Exception:
            logger.exception('redis_lock_acquire_error')
            lock_acquired = False

    if lock_key and not lock_acquired:
        msg = f'device {device_id} is currently being collected by another worker'
        logger.info(msg, extra={'device_id': device_id})
        return {
            'task_id': self.request.id if hasattr(self, 'request') else None,
            'status': 'failure',
            'timestamp': datetime.utcnow().isoformat() + 'Z',
            'log': [msg],
            'device_config': None,
        }

    # Execute plugin
    try:
        plugin_key = cfg.get('backup_method')
        plugin = get_plugin(plugin_key)
        if not plugin:
            raise RuntimeError(f'unknown backup method: {plugin_key}')

        # Ensure config contains ip and credentials
        plugin_cfg = {'ip': cfg.get('ip'), 'credentials': cfg.get('credentials', {}), **cfg.get('plugin_params', {})}

        logger.info(
            'starting_collection',
            extra={
                'device_id': device_id,
                'plugin': plugin_key,
                'queue': self.request.delivery_info.get('routing_key')
                if hasattr(self, 'request') and getattr(self.request, 'delivery_info', None)
                else None,
            },
        )

        # Capture start time for execution duration
        collection_start_ms = int(time.time() * 1000)

        result = plugin.run(plugin_cfg, timeout=timeout)

        # Capture end time and calculate duration
        collection_end_ms = int(time.time() * 1000)
        collection_duration_ms = collection_end_ms - collection_start_ms

        # Ensure result is a dict
        if not isinstance(result, dict):
            result = {
                'task_id': None,
                'status': 'failure',
                'timestamp': datetime.utcnow().isoformat() + 'Z',
                'log': ['invalid_plugin_result'],
                'device_config': None,
            }

        # Populate task_id and timing
        tid = getattr(self.request, 'id', None)
        result['task_id'] = tid
        result['collection_duration_ms'] = collection_duration_ms

        # Worker does NOT persist results or touch the DB — orchestrator is responsible.
        # Log a structured summary for observability and publish the result to a Redis Stream
        logger.info(
            'collection_result',
            extra={
                'task_id': tid,
                'task_identifier': task_identifier,
                'device_id': device_id,
                'status': result.get('status'),
                'collection_duration_ms': collection_duration_ms,
                'is_binary': plugin.is_binary,
            },
        )

        # Publish to Redis Stream for orchestrator consumption. Keep payload small and JSON-serializable.
        try:
            payload = {
                'task_id': tid or '',
                'task_identifier': task_identifier or '',
                'device_id': str(device_id) if device_id is not None else '',
                'status': result.get('status', ''),
                'log': json.dumps(result.get('log', [])),
                'device_config': result.get('device_config') or '',
                'collection_duration_ms': str(collection_duration_ms),
                'initiated_at': cfg.get('initiated_at', ''),
                'is_binary': str(plugin.is_binary),  # NEW: propagate binary flag
            }
            # redis-py requires mapping values to be bytes/str
            redis_client.xadd(COLLECT_RESULTS_STREAM, payload)
        except Exception:
            logger.exception('failed_to_publish_result')

        return result

    except SoftTimeLimitExceeded:
        msg = 'task_soft_time_limit_exceeded'
        logger.exception(msg)
        return {
            'task_id': getattr(self.request, 'id', None),
            'status': 'failure',
            'timestamp': datetime.utcnow().isoformat() + 'Z',
            'log': [msg],
            'device_config': None,
        }
    except Exception as exc:
        logger.exception('unhandled_collection_exception')
        # Celery autoretry_for will handle retrying according to decorator
        return {
            'task_id': getattr(self.request, 'id', None),
            'status': 'failure',
            'timestamp': datetime.utcnow().isoformat() + 'Z',
            'log': [f'unhandled: {repr(exc)}'],
            'device_config': None,
        }
    finally:
        if lock and lock_acquired:
            try:
                lock.release()
            except Exception:
                logger.exception('failed_to_release_lock')
