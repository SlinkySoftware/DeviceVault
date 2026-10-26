"""Tasks run by the orchestrator's `events` worker (queue dv.orchestrator)."""

import logging

from devicevault.celery import app
from devicevault_protocol.jobs import JOB_EVENT_TASK
from devicevault_protocol.monitoring import MONITORING_EVENT_TASK
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


@app.task(name=MONITORING_EVENT_TASK, ignore_result=True)
def monitoring_event(envelope: dict) -> None:
    from monitoring.relay import EventRejected as MonitoringEventRejected
    from monitoring.relay import handle_monitoring_event

    try:
        handle_monitoring_event(envelope)
    except MonitoringEventRejected:
        pass


# Orchestrator-internal (backups.changes, search.indexing), but on the same queue, so they are signed too.
CHANGE_SUMMARY_TASK = 'orchestrator.change_summary'
CHANGE_SUMMARY_RETRIES = 3
SEARCH_INDEX_TASK = 'orchestrator.search_index'


def _stored_job(envelope: dict, task: str):
    """The stored job a signed internal task names, or None (a forged task is logged and dropped)."""
    from backups import changes
    from backups.models import BackupJob
    from devicevault_protocol.signing import SignatureError

    try:
        job_id = changes.verified_job_id(envelope)
    except (SignatureError, KeyError, TypeError, ValueError) as exc:
        logger.warning(f'{task}_rejected', extra={'reason': str(exc)})
        return None
    return BackupJob.objects.select_related('device').filter(pk=job_id, state=BackupJob.STORED).first()


@app.task(
    bind=True, name=CHANGE_SUMMARY_TASK, ignore_result=True, max_retries=CHANGE_SUMMARY_RETRIES, soft_time_limit=300
)
def change_summary(self, envelope: dict) -> None:
    """Summarise a stored backup's changes and, with config search on, index it from the same read."""
    from search import indexing

    from backups import changes
    from backups.content import ContentDeleted, ContentUnavailable

    job = _stored_job(envelope, 'change_summary')
    if job is None:
        return
    read = changes.reader()
    try:
        if indexing.enabled() and not job.pruned:
            indexing.index_job(job, read=read)
        changes.summarise(job, read=read)
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


@app.task(
    bind=True, name=SEARCH_INDEX_TASK, ignore_result=True, max_retries=CHANGE_SUMMARY_RETRIES, soft_time_limit=300
)
def search_index(self, envelope: dict) -> None:
    """Index a stored backup for config search (queued by the scheduler's catch-up pass)."""
    from search import indexing

    from backups.content import ContentUnavailable

    job = _stored_job(envelope, 'search_index')
    if job is None or job.pruned or not indexing.enabled():
        return
    try:
        indexing.index_job(job)
    except ContentUnavailable as exc:
        if self.request.retries < self.max_retries:
            raise self.retry(countdown=60 * 2**self.request.retries) from exc
        # The catch-up pass queues it again later.
        logger.warning('search_index_failed', extra={'job_id': str(job.pk), 'reason': str(exc)})
