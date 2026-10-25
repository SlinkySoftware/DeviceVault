"""Task, queue and key names shared by the orchestrator and workers."""

COLLECT_TASK = 'job.collect'
STORE_TASK = 'job.store'
READ_TASK = 'storage.read'
CHECK_TASK = 'storage.check'
DELETE_TASK = 'storage.delete'


def collection_queue_name(queue_id: str) -> str:
    return f'collector.group.{queue_id}'


def storage_target_queue_name(target_id) -> str:
    """The queue a storage target's workers consume (store, read and check tasks)."""
    return f'storage.target.{target_id}'


def device_lock_key(device_id) -> str:
    return f'dv:lock:device:{device_id}'
