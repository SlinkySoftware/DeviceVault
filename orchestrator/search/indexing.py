"""Building config search documents (ARCHITECTURE.md section 7.2).

Each device has one ``SearchDocument``: the text of its newest stored backup, with
secret values replaced by tokens. The post-store task (``orchestrator.change_summary``)
indexes a backup from the bytes it already read for the summary. The scheduler's
catch-up pass (``catch_up``) queues ``SEARCH_INDEX_TASK`` for every device whose
document is missing or stale: search just turned on, a failed read, a rotated data
key, or changed secret patterns. With search off, it deletes every document.
"""

import logging
from collections.abc import Callable
from datetime import datetime, timedelta
from functools import cache

from django.conf import settings
from django.db import transaction
from django.db.models import OuterRef, Subquery
from redis import Redis

from backups.changes import MAX_SUMMARY_BYTES
from backups.content import read_content
from backups.models import BackupJob
from core import keys
from core.signing import sign_task
from core.tasks import SEARCH_INDEX_TASK
from core.workers import driver_catalogue
from devices.models import Device
from devicevault.celery import app as celery_app
from devicevault_protocol.registration import ORCHESTRATOR_QUEUE
from search.models import SearchDocument
from search.tokens import SecretPatterns, compile_patterns, tokenise_text

logger = logging.getLogger('devicevault.search')

MAX_INDEX_BYTES = MAX_SUMMARY_BYTES
CATCH_UP_INTERVAL = timedelta(minutes=5)
CATCH_UP_BATCH = 200
# A device queued by the catch-up pass is not queued again for this long (its task may be retrying).
QUEUED_KEY = 'dv:search:queued:{device}'
QUEUED_SECONDS = 3600
_last_catch_up: datetime | None = None


def enabled() -> bool:
    return settings.DEVICEVAULT_CONFIG_SEARCH


@cache
def _redis() -> Redis:
    return Redis.from_url(settings.DEVICEVAULT_BUS.redis_url)


def driver_patterns(driver: str, catalogue: dict | None = None) -> SecretPatterns:
    """The secret patterns of collector driver ``driver``, as approved collectors advertise them."""
    catalogue = driver_catalogue() if catalogue is None else catalogue
    return compile_patterns((catalogue.get(driver) or {}).get('secret_lines'))


def _is_current(document: SearchDocument | None, driver: str, kid: str, patterns: SecretPatterns) -> bool:
    """Whether ``document`` was built the way a document of ``driver`` is built now."""
    return (
        document is not None
        and document.driver == driver
        and document.token_kid == kid
        and document.patterns_hash == patterns.fingerprint
    )


def index_job(job: BackupJob, read: Callable[[BackupJob], bytes] | None = None) -> SearchDocument:
    """Make ``job`` (stored) its device's search document, unless a newer backup already is.

    ``read`` reads a backup's plaintext (default ``backups.content.read_content``).
    Raises ``ContentUnavailable`` when the backup cannot be read back right now.
    """
    read = read or read_content
    device = job.device
    document = SearchDocument.objects.select_related('job').filter(device=device).first()
    if document is not None and document.job.created_at > job.created_at:
        return document  # tasks ran out of order
    driver = device.backup_method
    patterns = driver_patterns(driver)
    kid = keys.search_token_key()[0]
    current = _is_current(document, driver, kid, patterns)
    if current and document.job_id == job.pk:
        return document

    fields = {'job': job, 'driver': driver, 'token_kid': kid, 'patterns_hash': patterns.fingerprint, 'skipped': ''}
    if job.is_binary:
        fields.update(text='', skipped='binary backup')
    elif (job.size_bytes or 0) > MAX_INDEX_BYTES:
        fields.update(text='', skipped=f'larger than {MAX_INDEX_BYTES // (1024 * 1024)} MiB')
    elif (
        current
        and not document.skipped
        and not (job.encrypted or document.job.encrypted)
        and job.stored_sha256 == document.job.stored_sha256
    ):
        pass  # the same content as the document's backup: it just moves to this one
    else:
        text = read(job).decode('utf-8', 'replace').replace('\r\n', '\n')
        fields['text'] = tokenise_text(text, patterns)

    with transaction.atomic():
        locked = SearchDocument.objects.select_for_update().select_related('job').filter(device=device).first()
        if locked is not None and locked.job.created_at > job.created_at:
            return locked  # a newer backup was indexed meanwhile
        document, _ = SearchDocument.objects.update_or_create(device=device, defaults=fields)
    return document


def request_index(job_id: str) -> None:
    celery_app.send_task(SEARCH_INDEX_TASK, args=[sign_task({'job_id': job_id})], queue=ORCHESTRATOR_QUEUE)


def stale_jobs() -> list[tuple[int, str]]:
    """``(device id, job id)`` of each device's newest stored backup whose document is missing or stale."""
    newest = (
        BackupJob.objects.filter(
            device=OuterRef('pk'),
            state=BackupJob.STORED,
            prune_requested_at__isnull=True,
            pruned_at__isnull=True,
        )
        .order_by('-created_at')
        .values('pk')[:1]
    )
    rows = (
        Device.objects.annotate(newest_job=Subquery(newest))
        .filter(newest_job__isnull=False)
        .values_list('pk', 'newest_job', 'backup_method')
    )
    documents = {
        document['device_id']: document
        for document in SearchDocument.objects.values('device_id', 'job_id', 'driver', 'token_kid', 'patterns_hash')
    }
    kid = keys.search_token_key()[0]
    catalogue = driver_catalogue()
    fingerprints = {}
    stale = []
    for device_id, job_id, driver in rows:
        if driver not in fingerprints:
            fingerprints[driver] = driver_patterns(driver, catalogue).fingerprint
        document = documents.get(device_id)
        if document is None or (
            document['job_id'] != job_id
            or document['driver'] != driver
            or document['token_kid'] != kid
            or document['patterns_hash'] != fingerprints[driver]
        ):
            stale.append((device_id, str(job_id)))
    return stale


def queue_stale(limit: int | None = None, *, force: bool = False) -> int:
    """Queue index tasks for up to ``limit`` stale devices not queued within the hour (any, with ``force``).

    Returns how many were queued.
    """
    redis = _redis()
    queued = 0
    for device_id, job_id in stale_jobs():
        if limit is not None and queued >= limit:
            break
        key = QUEUED_KEY.format(device=device_id)
        if force:
            redis.set(key, job_id, ex=QUEUED_SECONDS)
        elif not redis.set(key, job_id, ex=QUEUED_SECONDS, nx=True):
            continue
        request_index(job_id)
        queued += 1
    return queued


def catch_up(now: datetime) -> int | None:
    """Run the catch-up pass if the last one was over ``CATCH_UP_INTERVAL`` ago. Tasks queued, or None.

    With search off it deletes every document instead.
    """
    global _last_catch_up
    if _last_catch_up is not None and now - _last_catch_up < CATCH_UP_INTERVAL:
        return None
    _last_catch_up = now
    if not enabled():
        deleted, _ = SearchDocument.objects.all().delete()
        if deleted:
            logger.info('search_index_deleted', extra={'documents': deleted})
        return 0
    return queue_stale(CATCH_UP_BATCH)
