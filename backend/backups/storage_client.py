"""Thin client helpers for synchronous storage worker interactions."""

from typing import Any, Dict, Optional

from celery_app import app as celery_app


def read_backup_via_worker(
    storage_backend: str,
    storage_ref: str,
    storage_config: Dict[str, Any],
    *,
    task_identifier: Optional[str] = None,
    is_binary: bool = False,
    timeout: int = 60,
) -> Dict[str, Any]:
    """Fetch backup content by delegating to the storage.read Celery task.
    
    Args:
        storage_backend: Storage backend name (e.g., 'filesystem', 'git').
        storage_ref: Opaque reference to backup artifact.
        storage_config: Backend-specific configuration.
        task_identifier: Optional task identifier for logging.
        is_binary: True if backup is binary, False if text (default).
        timeout: Request timeout in seconds.
    
    Returns:
        Dict with 'content' (str or base64-encoded for binary) and metadata.
    """
    queue = f'storage.{storage_backend}'
    task = celery_app.send_task(
        'storage.read',
        kwargs={
            'storage_backend': storage_backend,
            'storage_ref': storage_ref,
            'storage_config': storage_config,
            'task_identifier': task_identifier,
            'is_binary': is_binary,        },
        queue=queue,
        routing_key=queue,
    )
    return task.get(timeout=timeout)