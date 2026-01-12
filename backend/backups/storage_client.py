"""Thin client helpers for synchronous storage worker interactions."""

from typing import Any, Dict, Optional

from celery_app import app as celery_app


def read_backup_via_worker(
    storage_backend: str,
    storage_ref: str,
    storage_config: Dict[str, Any],
    *,
    task_identifier: Optional[str] = None,
    timeout: int = 60,
) -> Dict[str, Any]:
    """Fetch backup content by delegating to the storage.read Celery task."""
    queue = f'storage.{storage_backend}'
    task = celery_app.send_task(
        'storage.read',
        kwargs={
            'storage_backend': storage_backend,
            'storage_ref': storage_ref,
            'storage_config': storage_config,
            'task_identifier': task_identifier,
        },
        queue=queue,
        routing_key=queue,
    )
    return task.get(timeout=timeout)
