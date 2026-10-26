"""The backup job pipeline.

    orchestrator --job.collect--> collector --job.store--> storage worker
         ^                           |                          |
         +------ job events (signed by the worker, on dv.orchestrator) ------+

1. The orchestrator creates a BackupJob and sends ``job.collect`` (signed by
   the orchestrator) to the device's collection group queue. Its payload
   includes a separate orchestrator-signed ``store`` envelope for the storage
   step and the storage queue to send it to.
2. The collector collects, optionally encrypts, stages the bytes in Redis
   under ``blob_key(job_id)`` and sends ``job.store`` to the storage queue with
   args ``[store_envelope, blob]``, where ``blob`` is
   ``{"key", "sha256", "size"}``. Backups never travel through RabbitMQ.
3. The storage worker fetches the blob, checks its hash, writes it and
   deletes the blob.

Each step reports a ``JOB_EVENT_TASK`` event, a worker-signed envelope whose
payload is::

    {"job_id": "<uuid>", "event": "started" | "retrying" | "collected" | "stored" | "failed",
     "worker_id": "<uuid>", "attempt": 1, "log": [<log entry>, ...], ...}

``collected`` adds ``sha256``, ``size``, ``is_binary``, ``encrypted``,
``duration_ms``; ``stored`` adds ``sha256``, ``size``, ``storage_ref``,
``duration_ms``; ``retrying`` and ``failed`` add ``error`` and ``stage``
("collect" or "store"); ``failed`` also adds ``reason``, one of
``FAILURE_REASONS``. The orchestrator stores it as ``BackupJob.failure_reason``
(mapping anything it does not recognise to ``unknown``) and sets
``integrity``, ``storage`` and ``orphaned`` itself.
The orchestrator only accepts a ``stored`` event whose hash matches the one
the collector reported.

Retention: the orchestrator sends ``storage.delete`` (signed) to a storage
target's queue with ``items`` (``[{"job_id", "storage_ref"}, ...]``); the
storage worker reports ``deleted`` or ``delete_failed`` (adds ``error``) per
item. The orchestrator only accepts them for a deletion it asked for, from a
worker serving that backup's target.

Log entries: ``{"source", "timestamp", "severity", "message"}``.
"""

JOB_EVENT_TASK = 'orchestrator.job_event'

EVENT_STARTED = 'started'
EVENT_RETRYING = 'retrying'
EVENT_COLLECTED = 'collected'
EVENT_STORED = 'stored'
EVENT_FAILED = 'failed'
# Retention: a storage worker deleted a stored backup, or could not.
EVENT_DELETED = 'deleted'
EVENT_DELETE_FAILED = 'delete_failed'
EVENTS = (
    EVENT_STARTED,
    EVENT_RETRYING,
    EVENT_COLLECTED,
    EVENT_STORED,
    EVENT_FAILED,
    EVENT_DELETED,
    EVENT_DELETE_FAILED,
)

STAGE_COLLECT = 'collect'
STAGE_STORE = 'store'

# Why a job failed (``BackupJob.failure_reason``). Monitoring exposes these, never the error text.
FAILURE_CONNECTION = 'connection'  # unreachable, refused, or DNS
FAILURE_AUTH = 'auth'  # login or enable refused
FAILURE_TIMEOUT = 'timeout'  # the device stopped answering mid-session
FAILURE_COMMAND = 'command'  # the device rejected a command
FAILURE_VERIFICATION = 'verification'  # reserved (ROADMAP Q12)
FAILURE_STORAGE = 'storage'  # the storage worker failed
FAILURE_INTEGRITY = 'integrity'  # hash mismatch
FAILURE_PUSH = 'push'  # a pushed file could not be ingested
FAILURE_ORPHANED = 'orphaned'  # the orchestrator's job timeout fired
FAILURE_UNKNOWN = 'unknown'
FAILURE_REASONS = (
    FAILURE_CONNECTION,
    FAILURE_AUTH,
    FAILURE_TIMEOUT,
    FAILURE_COMMAND,
    FAILURE_VERIFICATION,
    FAILURE_STORAGE,
    FAILURE_INTEGRITY,
    FAILURE_PUSH,
    FAILURE_ORPHANED,
    FAILURE_UNKNOWN,
)


def failure_reason(value: object) -> str:
    """``value`` if it is a known failure reason, else ``unknown``."""
    return value if isinstance(value, str) and value in FAILURE_REASONS else FAILURE_UNKNOWN


# Staged backups live long enough for a storage worker outage to be fixed.
BLOB_TTL_SECONDS = 24 * 3600
# Content read back for the UI is fetched immediately.
READ_BLOB_TTL_SECONDS = 600


def blob_key(job_id: str) -> str:
    return f'dv:blob:job:{job_id}'


def read_blob_key(request_id: str) -> str:
    return f'dv:blob:read:{request_id}'
