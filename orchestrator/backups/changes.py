"""Change summaries: how a stored backup differs from the device's previous one.

When a job is stored, ``backups.jobs`` queues ``CHANGE_SUMMARY_TASK`` (signed, on the
orchestrator's own queue, run by the ``events`` process). ``summarise`` reads both
backups back, decrypting them when payload encryption is on (the orchestrator is the
only place that can), drops the lines the device's collector driver declares volatile
(so a pushed file's "Last configuration change" banner is not a change), and records
whether anything changed and how many lines were added, removed and modified.

The previous backup is the device's newest stored backup before this one that
retention has not deleted. Binary backups are only compared for equality. Two
unencrypted backups with the same hash are unchanged without being read.
"""

import logging
import re
from collections.abc import Callable
from datetime import timedelta
from difflib import SequenceMatcher

from backups.content import read_content
from backups.models import BackupJob
from core.signing import public_key, sign_task
from core.tasks import CHANGE_SUMMARY_TASK
from core.workers import driver_catalogue
from devicevault.celery import app as celery_app
from devicevault_protocol import signing
from devicevault_protocol.registration import ORCHESTRATOR_QUEUE
from devicevault_protocol.tasks import ORCHESTRATOR_SIGNER

logger = logging.getLogger('devicevault.changes')

# Larger backups (pushed archives, say) are not read back just to be compared.
MAX_SUMMARY_BYTES = 16 * 1024 * 1024
TASK_MAX_AGE = timedelta(days=1)
_NO_SUMMARY = {'changed': None, 'lines_added': None, 'lines_removed': None, 'lines_modified': None}


def request_summary(job: BackupJob) -> None:
    """Queue the summary of a stored job (call it once the job is committed)."""
    celery_app.send_task(CHANGE_SUMMARY_TASK, args=[sign_task({'job_id': str(job.id)})], queue=ORCHESTRATOR_QUEUE)


def verified_job_id(envelope) -> str:
    """The job id of an internal task (summary, search index) the orchestrator itself signed.

    Workers can publish to its queue too, so anything else raises ``signing.SignatureError``.
    """
    if not isinstance(envelope, dict) or envelope.get('signer') != ORCHESTRATOR_SIGNER:
        raise signing.SignatureError('change summaries are only requested by the orchestrator')
    payload = signing.verify(envelope, signing.public_key_from_b64(public_key()), max_age=TASK_MAX_AGE)
    return str(payload['job_id'])


def previous_backup(job: BackupJob) -> BackupJob | None:
    """The device's newest stored backup before ``job`` whose content is still there."""
    return (
        BackupJob.objects.filter(
            device_id=job.device_id,
            state=BackupJob.STORED,
            created_at__lt=job.created_at,
            prune_requested_at__isnull=True,
            pruned_at__isnull=True,
        )
        .exclude(pk=job.pk)
        .order_by('-created_at')
        .first()
    )


def volatile_pattern(device) -> re.Pattern | None:
    """Lines of ``device``'s backups that change on every read, per its collector driver."""
    if (device.driver_params or {}).get('strip_volatile') is False:
        return None
    patterns = (driver_catalogue().get(device.backup_method) or {}).get('volatile_lines') or []
    return re.compile('|'.join(f'(?:{pattern})' for pattern in patterns)) if patterns else None


def text_lines(data: bytes, volatile: re.Pattern | None = None) -> list[str]:
    lines = data.decode('utf-8', 'replace').replace('\r\n', '\n').split('\n')
    if volatile is not None:
        lines = [line for line in lines if not volatile.match(line.lstrip())]
    while lines and lines[-1] == '':
        lines.pop()
    return lines


def count_changes(old: list[str], new: list[str]) -> tuple[int, int, int]:
    """Lines added, removed and modified going from ``old`` to ``new``.

    As in the compare view, a run of removed lines replaced by a run of added ones pairs up line by
    line as modified; whatever is left over on either side is removed or added.
    """
    added = removed = modified = 0
    for tag, i1, i2, j1, j2 in SequenceMatcher(None, old, new).get_opcodes():
        paired = min(i2 - i1, j2 - j1) if tag == 'replace' else 0
        modified += paired
        if tag in ('replace', 'delete'):
            removed += i2 - i1 - paired
        if tag in ('replace', 'insert'):
            added += j2 - j1 - paired
    return added, removed, modified


def reader() -> Callable[[BackupJob], bytes]:
    """``read_content`` that reads each backup once, so the summary and the search index share a read."""
    contents: dict = {}

    def read(job: BackupJob) -> bytes:
        if job.pk not in contents:
            contents[job.pk] = read_content(job)
        return contents[job.pk]

    return read


def summarise(job: BackupJob, read: Callable[[BackupJob], bytes] | None = None) -> BackupJob:
    """Work out and save how ``job`` differs from the previous backup.

    ``read`` reads a backup's plaintext (default ``read_content``). Raises
    ``ContentUnavailable`` when a backup cannot be read back right now.
    """
    read = read or read_content
    previous = previous_backup(job)
    binary = job.is_binary or bool(previous and previous.is_binary)
    summary = {'compared_to': previous, **_NO_SUMMARY}

    if previous and not (job.encrypted or previous.encrypted) and job.stored_sha256 == previous.stored_sha256:
        count = None if binary else 0
        summary.update(changed=False, lines_added=count, lines_removed=count, lines_modified=count)
    elif any((backup.size_bytes or 0) > MAX_SUMMARY_BYTES for backup in (job, previous) if backup):
        return _save(job, summary, error=f'larger than {MAX_SUMMARY_BYTES // (1024 * 1024)} MiB, not compared')
    else:
        new = read(job)
        old = read(previous) if previous else None
        if binary:
            summary['changed'] = old != new
        else:
            volatile = volatile_pattern(job.device)
            added, removed, modified = count_changes(
                text_lines(old, volatile) if old is not None else [], text_lines(new, volatile)
            )
            summary.update(
                changed=previous is None or bool(added or removed or modified),
                lines_added=added,
                lines_removed=removed,
                lines_modified=modified,
            )
    return _save(job, summary)


def _save(job: BackupJob, summary: dict, error: str = '') -> BackupJob:
    for field, value in {**summary, 'summary_error': error[:255]}.items():
        setattr(job, field, value)
    BackupJob.objects.filter(pk=job.pk).update(**summary, summary_error=error[:255])
    return job


def record_failure(job: BackupJob, error: str) -> None:
    """Give up on ``job``'s summary, saying why."""
    _save(job, {'compared_to': None, **_NO_SUMMARY}, error=error)
