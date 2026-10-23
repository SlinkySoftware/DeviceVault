"""Task, queue and key names shared by the orchestrator and workers."""

COLLECT_TASK = 'job.collect'
STORE_TASK = 'job.store'
READ_TASK = 'storage.read'

# Backup location types (as configured in the orchestrator) mapped to the
# storage backend key a storage worker serves.
_STORAGE_BACKEND_ALIASES = {
    'git': 'git',
    'fs': 'fs',
    'filesystem': 'fs',
}
STORAGE_BACKENDS = frozenset(_STORAGE_BACKEND_ALIASES.values())


def collection_queue_name(queue_id: str) -> str:
    return f'collector.group.{queue_id}'


def storage_backend_for(location_type: str | None) -> str | None:
    """Return the storage backend key for a location type, or None if unsupported."""
    return _STORAGE_BACKEND_ALIASES.get((location_type or '').strip().lower())


def storage_queue_name(storage_backend: str) -> str:
    return f'storage.{storage_backend}'


def device_lock_key(device_id) -> str:
    return f'dv:lock:device:{device_id}'
