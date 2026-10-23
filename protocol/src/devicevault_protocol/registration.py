"""Worker registration protocol.

Worker -> orchestrator: Celery task ``WORKER_EVENT_TASK`` on ``ORCHESTRATOR_QUEUE``,
argument a signed envelope (signed with the worker's own key) whose payload is::

    {"event": "register" | "heartbeat",
     "worker_id": "<uuid>", "name": "...", "celery_hostname": "name@host",
     "hostname": "...", "pid": 123, "version": "0.1.0",
     "signing_key": "<b64 Ed25519 public>", "encryption_key": "<b64 X25519 public>",
     "capabilities": {"collector_drivers": [{"key", "name", "version", "is_binary", "params_schema", ...}],
                      "storage_drivers": [{"key", "name", "version", "shareable", "params_schema", ...}]},
     "applied_version": 0,                 # assignment version currently in effect
     "orchestrator_key": "<b64>" | null}   # pinned orchestrator key, if any

Orchestrator -> worker: a plain message on the worker's control queue, a
signed envelope (orchestrator key) whose payload is::

    {"type": "assignment", "worker_id": "<uuid>", "version": 3,
     "status": "pending" | "approved" | "revoked",
     "role": "collector" | "storage" | "", "queues": ["collector.group.dmz" | "storage.target.<uuid>"],
     "orchestrator_key": "<b64 Ed25519 public>"}

The worker pins ``orchestrator_key`` on the first assignment it accepts
(trust on first use) and rejects any later key.
"""

from datetime import timedelta

ORCHESTRATOR_QUEUE = 'dv.orchestrator'
WORKER_EVENT_TASK = 'orchestrator.worker_event'

EVENT_REGISTER = 'register'
EVENT_HEARTBEAT = 'heartbeat'
ASSIGNMENT = 'assignment'

STATUS_PENDING = 'pending'
STATUS_APPROVED = 'approved'
STATUS_REVOKED = 'revoked'

ROLE_COLLECTOR = 'collector'
ROLE_STORAGE = 'storage'
ROLES = (ROLE_COLLECTOR, ROLE_STORAGE)

# Stale events are useless (a newer heartbeat follows), so they expire in the queue.
EVENT_EXPIRES_SECONDS = 120
# Assignments older than this are ignored, limiting replay of captured messages.
ASSIGNMENT_MAX_AGE = timedelta(minutes=15)


def control_queue_name(worker_id: str) -> str:
    """Per-worker queue for orchestrator control messages (assignments)."""
    return f'dv.worker.{worker_id}.control'


def direct_queue_name(worker_id: str) -> str:
    """Per-worker Celery task queue the worker always consumes."""
    return f'dv.worker.{worker_id}'
