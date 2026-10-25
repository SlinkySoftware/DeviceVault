"""Tasks run by the orchestrator's `events` worker (queue dv.orchestrator)."""

import logging

from devicevault.celery import app
from devicevault_protocol.jobs import JOB_EVENT_TASK
from devicevault_protocol.push import PUSH_EVENT_TASK
from devicevault_protocol.registration import WORKER_EVENT_TASK

from .workers import EventRejected, handle_event

logger = logging.getLogger('devicevault.tasks')


@app.task(name=WORKER_EVENT_TASK, ignore_result=True)
def worker_event(envelope: dict) -> None:
    try:
        handle_event(envelope)
    except EventRejected:
        # Already logged; a forged or stale event must not be retried.
        pass


@app.task(name=JOB_EVENT_TASK, ignore_result=True)
def job_event(envelope: dict) -> None:
    from backups.jobs import EventRejected as JobEventRejected
    from backups.jobs import handle_job_event

    try:
        handle_job_event(envelope)
    except JobEventRejected:
        pass


@app.task(name=PUSH_EVENT_TASK, ignore_result=True)
def push_event(envelope: dict) -> None:
    from push.events import EventRejected as PushEventRejected
    from push.events import handle_push_event

    try:
        handle_push_event(envelope)
    except PushEventRejected:
        pass


# Orchestrator-internal (backups.changes), but on the same queue, so it is signed too.
CHANGE_SUMMARY_TASK = 'orchestrator.change_summary'
CHANGE_SUMMARY_RETRIES = 3


@app.task(
    bind=True, name=CHANGE_SUMMARY_TASK, ignore_result=True, max_retries=CHANGE_SUMMARY_RETRIES, soft_time_limit=300
)
def change_summary(self, envelope: dict) -> None:
    from backups import changes
    from backups.content import ContentDeleted, ContentUnavailable
    from backups.models import BackupJob
    from devicevault_protocol.signing import SignatureError

    try:
        job_id = changes.verified_job_id(envelope)
    except (SignatureError, KeyError, TypeError, ValueError) as exc:
        logger.warning('change_summary_rejected', extra={'reason': str(exc)})
        return
    job = BackupJob.objects.select_related('device').filter(pk=job_id, state=BackupJob.STORED).first()
    if job is None:
        return
    try:
        changes.summarise(job)
    except ContentDeleted as exc:
        if job.pruned:
            changes.record_failure(job, str(exc))
            return
        # The previous backup was deleted meanwhile; compare with the one before it.
        raise self.retry(countdown=1) from exc
    except ContentUnavailable as exc:
        if self.request.retries < self.max_retries:
            raise self.retry(countdown=60 * 2**self.request.retries) from exc
        changes.record_failure(job, str(exc))
