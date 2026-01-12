"""
Celery tasks for storage backends (Git, filesystem).
These tasks are intentionally standalone and avoid Django imports.
"""

import json
import logging
import os
import re
from datetime import datetime
from typing import Dict, List, Optional

from celery.exceptions import SoftTimeLimitExceeded
from pythonjsonlogger import jsonlogger  # type: ignore
from redis import Redis

from celery_app import app as celery_app, REDIS_URL, STORAGE_RESULTS_STREAM
from storage import git as git_storage
from storage import fs as fs_storage

# Provide app alias for Celery discovery
app = celery_app

logger = logging.getLogger('devicevault.storage.worker')
_handler = logging.StreamHandler()
_formatter = jsonlogger.JsonFormatter('%(asctime)s %(levelname)s %(name)s %(message)s')  # type: ignore
_handler.setFormatter(_formatter)
logger.addHandler(_handler)
logger.setLevel(os.environ.get('DEVICEVAULT_LOG_LEVEL', 'INFO'))

redis_client = Redis.from_url(REDIS_URL)

STORAGE_BACKENDS = {
    'git': {
        'store': git_storage.store_backup,
        'read': git_storage.read_backup,
    },
    'fs': {
        'store': fs_storage.store_backup,
        'read': fs_storage.read_backup,
    },
    'filesystem': {
        'store': fs_storage.store_backup,
        'read': fs_storage.read_backup,
    },
}


def _iso_now() -> str:
    return datetime.utcnow().isoformat() + 'Z'


def _storage_queue_name(storage_backend: str) -> str:
    return f'storage.{storage_backend}' if storage_backend else 'storage'


def _sanitize_rel_path(device_id: Optional[int], task_identifier: str) -> str:
    safe_identifier = re.sub(r'[^A-Za-z0-9_.-]', '-', task_identifier or 'job')
    prefix = str(device_id) if device_id is not None else 'unknown'
    return f"{prefix}/{safe_identifier}.txt"


def _publish_result(result: Dict) -> None:
    try:
        payload = {
            'task_id': result.get('task_id', '') or '',
            'task_identifier': result.get('task_identifier', '') or '',
            'device_id': str(result.get('device_id') or ''),
            'status': result.get('status', '') or '',
            'log': json.dumps(result.get('log', [])),
            'storage_backend': result.get('storage_backend', '') or '',
            'storage_ref': result.get('storage_ref', '') or '',
            'operation': result.get('operation', '') or 'store',
        }
        redis_client.xadd(STORAGE_RESULTS_STREAM, payload)  # type: ignore
    except Exception:
        logger.exception('storage_result_publish_failed')


@app.task(
    bind=True,
    name='storage.store',
    soft_time_limit=300,
    time_limit=360,
    acks_late=True,
    autoretry_for=(Exception,),
    retry_backoff=True,
    retry_kwargs={'max_retries': 3},
)
def storage_store_task(self, payload: Dict) -> Dict:
    """Store backup content using the configured storage backend.

    Expected payload keys:
        - storage_backend: git | fs
        - storage_config: dict
        - device_config: str (raw backup content)
        - task_identifier: logical job id
        - device_id: int
        - storage_rel_path: optional relative path override
    """
    log_lines: List[str] = []

    if isinstance(payload, str):
        try:
            payload = json.loads(payload)
        except Exception:
            payload = {}

    storage_backend = payload.get('storage_backend')
    storage_config = payload.get('storage_config') or {}
    device_config = payload.get('device_config')
    task_identifier = payload.get('task_identifier') or f'storage:{_iso_now()}'
    device_id = payload.get('device_id')
    rel_path = payload.get('storage_rel_path')
    operation = 'store'

    tid = getattr(getattr(self, 'request', None), 'id', None)

    if not storage_backend or storage_backend not in STORAGE_BACKENDS:
        msg = f'unsupported storage backend: {storage_backend}'
        log_lines.append(msg)
        result = {
            'task_id': tid,
            'task_identifier': task_identifier,
            'device_id': device_id,
            'storage_backend': storage_backend or '',
            'storage_ref': '',
            'status': 'failure',
            'timestamp': _iso_now(),
            'log': log_lines,
            'operation': operation,
        }
        _publish_result(result)
        return result

    if not device_config:
        msg = 'device_config missing; nothing to store'
        log_lines.append(msg)
        result = {
            'task_id': tid,
            'task_identifier': task_identifier,
            'device_id': device_id,
            'storage_backend': storage_backend,
            'storage_ref': '',
            'status': 'failure',
            'timestamp': _iso_now(),
            'log': log_lines,
            'operation': operation,
        }
        _publish_result(result)
        return result

    rel_path = rel_path or _sanitize_rel_path(device_id, task_identifier)

    try:
        logger.info(
            'storage_store_start',
            extra={
                'storage_backend': storage_backend,
                'device_id': device_id,
                'task_identifier': task_identifier,
                'queue': getattr(getattr(self, 'request', None), 'delivery_info', {}).get('routing_key'),
            },
        )
        storage_fn = STORAGE_BACKENDS[storage_backend]['store']
        storage_ref = storage_fn(str(device_config), rel_path, storage_config)
        log_lines.append(f'stored to {storage_backend}:{storage_ref}')
        result = {
            'task_id': tid,
            'task_identifier': task_identifier,
            'device_id': device_id,
            'storage_backend': storage_backend,
            'storage_ref': storage_ref,
            'status': 'success',
            'timestamp': _iso_now(),
            'log': log_lines,
            'operation': operation,
        }
        _publish_result(result)
        return result
    except SoftTimeLimitExceeded:
        msg = 'storage_task_soft_time_limit_exceeded'
        log_lines.append(msg)
        result = {
            'task_id': tid,
            'task_identifier': task_identifier,
            'device_id': device_id,
            'storage_backend': storage_backend,
            'storage_ref': '',
            'status': 'failure',
            'timestamp': _iso_now(),
            'log': log_lines,
            'operation': operation,
        }
        _publish_result(result)
        return result
    except Exception as exc:
        logger.exception('storage_store_failure')
        log_lines.append(f'unhandled: {repr(exc)}')
        result = {
            'task_id': tid,
            'task_identifier': task_identifier,
            'device_id': device_id,
            'storage_backend': storage_backend,
            'storage_ref': '',
            'status': 'failure',
            'timestamp': _iso_now(),
            'log': log_lines,
            'operation': operation,
        }
        _publish_result(result)
        return result


@app.task(
    bind=True,
    name='storage.read',
    soft_time_limit=120,
    time_limit=150,
    acks_late=True,
    autoretry_for=(Exception,),
    retry_backoff=True,
    retry_kwargs={'max_retries': 2},
)
def storage_read_task(
    self,
    storage_backend: str,
    storage_ref: str,
    storage_config: Dict,
    task_identifier: Optional[str] = None,
) -> Dict:
    """Retrieve backup content synchronously via the storage backend."""
    log_lines: List[str] = []
    tid = getattr(getattr(self, 'request', None), 'id', None)
    task_identifier = task_identifier or f'read:{storage_ref}'
    operation = 'read'

    if not storage_backend or storage_backend not in STORAGE_BACKENDS:
        msg = f'unsupported storage backend: {storage_backend}'
        log_lines.append(msg)
        result = {
            'task_id': tid,
            'task_identifier': task_identifier,
            'status': 'failure',
            'timestamp': _iso_now(),
            'log': log_lines,
            'storage_backend': storage_backend or '',
            'storage_ref': storage_ref,
            'operation': operation,
            'content': None,
        }
        _publish_result(result)
        return result

    try:
        logger.info(
            'storage_read_start',
            extra={'storage_backend': storage_backend, 'storage_ref': storage_ref},
        )
        read_fn = STORAGE_BACKENDS[storage_backend]['read']
        content = read_fn(storage_ref, storage_config)
        result = {
            'task_id': tid,
            'task_identifier': task_identifier,
            'status': 'success',
            'timestamp': _iso_now(),
            'log': log_lines,
            'storage_backend': storage_backend,
            'storage_ref': storage_ref,
            'operation': operation,
            'content': content,
        }
        return result
    except SoftTimeLimitExceeded:
        msg = 'storage_read_soft_time_limit_exceeded'
        log_lines.append(msg)
        result = {
            'task_id': tid,
            'task_identifier': task_identifier,
            'status': 'failure',
            'timestamp': _iso_now(),
            'log': log_lines,
            'storage_backend': storage_backend,
            'storage_ref': storage_ref,
            'operation': operation,
            'content': None,
        }
        _publish_result(result)
        return result
    except Exception as exc:
        logger.exception('storage_read_failure')
        log_lines.append(f'unhandled: {repr(exc)}')
        result = {
            'task_id': tid,
            'task_identifier': task_identifier,
            'status': 'failure',
            'timestamp': _iso_now(),
            'log': log_lines,
            'storage_backend': storage_backend,
            'storage_ref': storage_ref,
            'operation': operation,
            'content': None,
        }
        _publish_result(result)
        return result
