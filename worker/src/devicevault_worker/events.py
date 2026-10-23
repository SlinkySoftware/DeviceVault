"""Job events sent to the orchestrator, signed with this worker's key."""

from datetime import UTC, datetime
from typing import Any

from devicevault_protocol import signing
from devicevault_protocol.jobs import JOB_EVENT_TASK
from devicevault_protocol.registration import EVENT_EXPIRES_SECONDS, ORCHESTRATOR_QUEUE
from devicevault_worker.app import app, identity

# Job events matter (they complete jobs), so they outlive registration events.
JOB_EVENT_EXPIRES_SECONDS = max(EVENT_EXPIRES_SECONDS, 24 * 3600)


def send(job_id: str, event: str, **details: Any) -> None:
    payload = {
        'job_id': job_id,
        'event': event,
        'worker_id': identity.worker_id,
        'at': datetime.now(UTC).isoformat(),
        **details,
    }
    envelope = signing.sign(payload, identity.signing_key, identity.worker_id)
    app.send_task(JOB_EVENT_TASK, args=[envelope], queue=ORCHESTRATOR_QUEUE, expires=JOB_EVENT_EXPIRES_SECONDS)
