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
("collect" or "store").
The orchestrator only accepts a ``stored`` event whose hash matches the one
the collector reported.

Log entries: ``{"source", "timestamp", "severity", "message"}``.
"""

JOB_EVENT_TASK = 'orchestrator.job_event'

EVENT_STARTED = 'started'
EVENT_RETRYING = 'retrying'
EVENT_COLLECTED = 'collected'
EVENT_STORED = 'stored'
EVENT_FAILED = 'failed'
EVENTS = (EVENT_STARTED, EVENT_RETRYING, EVENT_COLLECTED, EVENT_STORED, EVENT_FAILED)

STAGE_COLLECT = 'collect'
STAGE_STORE = 'store'

# Staged backups live long enough for a storage worker outage to be fixed.
BLOB_TTL_SECONDS = 24 * 3600
# Content read back for the UI is fetched immediately.
READ_BLOB_TTL_SECONDS = 600


def blob_key(job_id: str) -> str:
    return f'dv:blob:job:{job_id}'


def read_blob_key(request_id: str) -> str:
    return f'dv:blob:read:{request_id}'
