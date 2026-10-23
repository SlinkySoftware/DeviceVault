"""
Celery tasks for storage backends (Git, filesystem).
These tasks are intentionally standalone and avoid Django imports.
"""

import json
import logging
import os
import re
import time
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

# ---------------------------------------------------------------------------
# Lazy-initialised encryption layer (standalone, no Django needed)
# ---------------------------------------------------------------------------
_crypto_storage = None
_crypto_checked = False


def _get_crypto_storage():
    """Return a CryptoStorage wrapper if a master key is configured, else None.

    Lazy-initialised on first call.  The storage worker process runs
    outside Django so we read config directly from env / YAML.

    With per-device encryption, the crypto subsystem must be available
    whenever keys are configured — regardless of the global ``enabled``
    flag.  The per-device ``encrypt_backup`` field in the payload
    controls whether encryption is actually applied to each backup.
    """
    global _crypto_storage, _crypto_checked
    if _crypto_checked:
        return _crypto_storage

    _crypto_checked = True
    try:
        from crypto.config import get_key_provider, get_chunk_size
        from crypto.wrapper import CryptoStorage

        kp = get_key_provider(force=True)
        if kp is None:
            logger.info('No encryption key provider available — per-device encryption will be unavailable')
            return None

        chunk_size = get_chunk_size()
        _crypto_storage = CryptoStorage(kp, chunk_size=chunk_size, encryption_enabled=True)
        logger.info(
            'Crypto subsystem ready: cipher=AES-256-GCM, chunk_size=%d, default_kid=%s',
            chunk_size, kp.get_default_key_id(),
        )
    except Exception as exc:
        # If crypto init fails, per-device encryption won't work.
        logger.error('Failed to initialise crypto storage: %s', exc)
        _crypto_storage = None

    return _crypto_storage


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
            'storage_duration_ms': str(result.get('storage_duration_ms', '') or ''),
            # Encryption metadata (empty strings for unencrypted backups)
            'enc_version': str(result.get('enc_version', '') or ''),
            'enc_cipher': result.get('enc_cipher', '') or '',
            'enc_kid': result.get('enc_kid', '') or '',
            'enc_edk': result.get('enc_edk', '') or '',
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
        log_lines.append({
            'source': 'storage_worker',
            'timestamp': _iso_now(),
            'severity': 'ERROR',
            'message': msg
        })
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
        log_lines.append({
            'source': 'storage_worker',
            'timestamp': _iso_now(),
            'severity': 'ERROR',
            'message': msg
        })
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
        
        # Capture start time for storage duration
        storage_start_ms = int(time.time() * 1000)
        
        storage_fn = STORAGE_BACKENDS[storage_backend]['store']
        is_binary = payload.get('is_binary', False)

        # Per-device encryption: the payload carries an 'encrypt_backup' flag
        # set by the device configuration. Only encrypt when the device opts in
        # AND the crypto subsystem is available (keys configured).
        encrypt_requested = payload.get('encrypt_backup', False)
        crypto = _get_crypto_storage() if encrypt_requested else None
        enc_meta = None
        if encrypt_requested and crypto is None:
            log_lines.append({
                'source': 'encryption',
                'timestamp': _iso_now(),
                'severity': 'WARNING',
                'message': 'Encryption requested but no master key is configured — backup stored as plaintext'
            })
            logger.warning(
                'encryption_requested_but_unavailable',
                extra={'device_id': device_id, 'task_identifier': task_identifier},
            )
        if crypto is not None:
            aad_fields = {
                'device_id': device_id,
                'task_identifier': task_identifier,
                'storage_backend': storage_backend,
            }
            storage_ref, enc_meta = crypto.store(
                str(device_config) if not is_binary else device_config,
                rel_path,
                storage_config,
                is_binary=is_binary,
                store_fn=storage_fn,
                aad_fields=aad_fields,
            )
        else:
            storage_ref = storage_fn(str(device_config), rel_path, storage_config)
        
        # Capture end time and calculate duration
        storage_end_ms = int(time.time() * 1000)
        storage_duration_ms = storage_end_ms - storage_start_ms
        
        enc_msg = ''
        if enc_meta:
            enc_msg = f' [encrypted v{enc_meta["enc_version"]}, kid={enc_meta["kid"]}]'
            log_lines.append({
                'source': 'encryption',
                'timestamp': _iso_now(),
                'severity': 'INFO',
                'message': f'Backup encrypted at rest (AES-256-GCM, key={enc_meta["kid"]})'
            })
        
        log_lines.append({
            'source': 'storage_worker',
            'timestamp': _iso_now(),
            'severity': 'INFO',
            'message': f'Stored to {storage_backend}:{storage_ref}{enc_msg} in {storage_duration_ms}ms'
        })
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
            'storage_duration_ms': storage_duration_ms,
        }
        # Attach encryption metadata to the result for persistence
        if enc_meta:
            result['enc_version'] = enc_meta.get('enc_version')
            result['enc_cipher'] = enc_meta.get('cipher')
            result['enc_kid'] = enc_meta.get('kid')
            result['enc_edk'] = enc_meta.get('edk')  # base64
        logger.info(
            'storage_store_complete',
            extra={
                'storage_backend': storage_backend,
                'device_id': device_id,
                'task_identifier': task_identifier,
                'storage_duration_ms': storage_duration_ms,
            },
        )
        _publish_result(result)
        return result
    except SoftTimeLimitExceeded:
        msg = 'storage_task_soft_time_limit_exceeded'
        log_lines.append({
            'source': 'storage_worker',
            'timestamp': _iso_now(),
            'severity': 'ERROR',
            'message': msg
        })
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
        log_lines.append({
            'source': 'storage_worker',
            'timestamp': _iso_now(),
            'severity': 'ERROR',
            'message': f'Unhandled exception: {repr(exc)}'
        })
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
    is_binary: bool = False,
) -> Dict:
    """Retrieve backup content synchronously via the storage backend."""
    log_lines: List[str] = []
    tid = getattr(getattr(self, 'request', None), 'id', None)
    task_identifier = task_identifier or f'read:{storage_ref}'
    operation = 'read'

    if not storage_backend or storage_backend not in STORAGE_BACKENDS:
        msg = f'unsupported storage backend: {storage_backend}'
        log_lines.append({
            'source': 'storage_worker',
            'timestamp': _iso_now(),
            'severity': 'ERROR',
            'message': msg
        })
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

        # Decryption: route through CryptoStorage if available (handles v0 plaintext transparently)
        crypto = _get_crypto_storage()
        if crypto is not None:
            content = crypto.read(storage_ref, storage_config, is_binary, read_fn=read_fn)
        else:
            content = read_fn(storage_ref, storage_config, is_binary=is_binary)
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
        log_lines.append({
            'source': 'storage_worker',
            'timestamp': _iso_now(),
            'severity': 'ERROR',
            'message': msg
        })
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
        log_lines.append({
            'source': 'storage_worker',
            'timestamp': _iso_now(),
            'severity': 'ERROR',
            'message': f'Unhandled exception: {repr(exc)}'
        })
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
