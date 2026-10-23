"""Tasks run by the orchestrator's `events` worker (queue dv.orchestrator)."""

from devicevault.celery import app
from devicevault_protocol.registration import WORKER_EVENT_TASK

from .workers import EventRejected, handle_event


@app.task(name=WORKER_EVENT_TASK, ignore_result=True)
def worker_event(envelope: dict) -> None:
    try:
        handle_event(envelope)
    except EventRejected:
        # Already logged; a forged or stale event must not be retried.
        pass
