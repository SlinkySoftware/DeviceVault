"""Dispatch device collection tasks to collector queues."""

import json

from django.utils import timezone

from devicevault.celery import app as celery_app
from devicevault_protocol.names import COLLECT_TASK, collection_queue_name


class DispatchError(Exception):
    """Raised when a device cannot be dispatched for collection."""


def dispatch_collection(device, trigger: str) -> tuple[str, str]:
    """Queue a collection task for ``device`` and return ``(task_id, queue)``.

    ``trigger`` prefixes the task identifier (for example ``backup_now``).
    """
    if not device.collection_group:
        raise DispatchError('Device has no collection group, so no collector can pick it up')

    now = timezone.now()
    cfg = {
        'device_id': device.id,
        'task_identifier': f'{trigger}:{device.id}:{now.isoformat()}',
        'ip': device.ip_address,
        'credentials': device.credential.data if device.credential else {},
        'backup_method': device.backup_method,
        'plugin_params': {},
        'timeout': 240,
        'initiated_at': now.isoformat(),
    }
    queue = collection_queue_name(device.collection_group.rabbitmq_queue_id)
    task = celery_app.send_task(COLLECT_TASK, args=[json.dumps(cfg)], queue=queue)
    return task.id, queue
