from datetime import timedelta

import pytest
from django.core.management import call_command
from django.utils import timezone

from backups import changes
from backups.content import ContentUnavailable
from backups.jobs import handle_job_event
from backups.models import BackupJob
from backups.tests.conftest import job_event
from core.signing import sign_task
from core.tasks import CHANGE_SUMMARY_RETRIES, CHANGE_SUMMARY_TASK, change_summary
from core.workers import _volatile_lines
from devicevault_protocol import signing
from devicevault_protocol.jobs import EVENT_COLLECTED, EVENT_STORED
from devicevault_protocol.tasks import sign_task as sign_with

NOW = timezone.now()
CISCO = ['Building configuration', r'! Last configuration change at']


@pytest.fixture
def contents(monkeypatch):
    """Backup contents by job, served instead of reading them from storage."""
    stored = {}

    def read(job):
        if job.pk not in stored:
            raise AssertionError(f'read {job.storage_ref}, which the test did not expect')
        value = stored[job.pk]
        if isinstance(value, Exception):
            raise value
        return value

    monkeypatch.setattr(changes, 'read_content', read)
    return stored


@pytest.fixture
def catalogue(monkeypatch):
    drivers = {'noop': {'volatile_lines': CISCO}}
    monkeypatch.setattr(changes, 'driver_catalogue', lambda: drivers)
    return drivers


@pytest.fixture
def backup(setup, contents, catalogue):
    """A stored backup of the device, ``hours`` ago, with ``content`` (encrypted by default, so it is read)."""

    def make(content: bytes | Exception = b'', *, hours=0, encrypted=True, sha='a' * 64, **fields):
        job = BackupJob.objects.create(
            device=setup['device'],
            state=BackupJob.STORED,
            driver='noop',
            storage_target=setup['target'],
            storage_driver='filesystem',
            storage_ref=f'ref-{hours}',
            stored_sha256=sha,
            size_bytes=len(content) if isinstance(content, bytes) else 10,
            encrypted=encrypted,
            **fields,
        )
        BackupJob.objects.filter(pk=job.pk).update(created_at=NOW - timedelta(hours=hours))
        job.refresh_from_db()
        contents[job.pk] = content
        return job

    return make


def summary(job):
    job.refresh_from_db()
    return job.changed, job.lines_added, job.lines_removed, job.lines_modified


def test_the_first_backup_counts_every_line_as_added(backup):
    job = changes.summarise(backup(b'hostname edge\ninterface Gi0/1\n'))

    assert summary(job) == (True, 2, 0, 0) and job.compared_to is None


def test_changed_lines_are_counted_against_the_previous_backup(backup):
    old = backup(b'a\nb\nc\n', hours=2)
    job = changes.summarise(backup(b'a\nB\nc\nd\n'))

    assert summary(job) == (True, 1, 0, 1) and job.compared_to == old


def test_replaced_runs_pair_up_as_modified_lines():
    # Two lines renamed in place and one dropped, as the compare view shows it: ~2 -1, not +2 -3.
    old = ['name=eoip-173crs', 'keep', 'interface=eoip-173crs', 'keep', 'drop me', 'end']
    new = ['name=eoip-nbn-via-173crs', 'keep', 'interface=eoip-nbn-via-173crs', 'keep', 'end']
    assert changes.count_changes(old, new) == (0, 1, 2)

    # A replaced run longer on one side leaves the rest added or removed.
    assert changes.count_changes(['a', 'x', 'b'], ['a', 'y', 'z', 'b']) == (1, 0, 1)
    assert changes.count_changes(['a', 'x', 'y', 'b'], ['a', 'z', 'b']) == (0, 1, 1)


def test_identical_backups_are_unchanged(backup):
    backup(b'a\nb\n', hours=1)

    assert summary(changes.summarise(backup(b'a\r\nb\r\n\r\n'))) == (False, 0, 0, 0)


def test_unencrypted_backups_with_the_same_hash_are_not_read(backup, contents):
    old = backup(b'', hours=1, encrypted=False)
    new = backup(b'', encrypted=False)
    del contents[old.pk], contents[new.pk]

    assert summary(changes.summarise(new)) == (False, 0, 0, 0)


def test_volatile_lines_of_the_devices_driver_are_ignored(setup, backup):
    """A pushed file's banner changes on every save; it is not a change."""
    backup(b'Building configuration...\n! Last configuration change at 01:00\nhostname edge\n', hours=1)
    pushed = backup(b'Building configuration...\n  ! Last configuration change at 02:00\nhostname edge\n')

    assert summary(changes.summarise(pushed)) == (False, 0, 0, 0)

    setup['device'].driver_params = {'strip_volatile': False}
    setup['device'].save()
    assert summary(changes.summarise(pushed)) == (True, 0, 0, 1)


def test_binary_backups_are_compared_for_equality_only(backup):
    backup(b'\x00\x01', hours=2, is_binary=True)
    same = backup(b'\x00\x01', hours=1, is_binary=True)
    other = backup(b'\x00\x02', is_binary=True)

    assert summary(changes.summarise(same)) == (False, None, None, None)
    assert summary(changes.summarise(other)) == (True, None, None, None)


def test_backups_deleted_by_retention_are_skipped(backup):
    backup(b'a\n', hours=3)
    backup(b'gone\n', hours=2, pruned_at=NOW)
    backup(b'going\n', hours=1, prune_requested_at=NOW)

    assert summary(changes.summarise(backup(b'a\n'))) == (False, 0, 0, 0)


def test_large_backups_are_not_compared(backup, monkeypatch):
    monkeypatch.setattr(changes, 'MAX_SUMMARY_BYTES', 4)
    backup(b'a\n', hours=1)
    job = changes.summarise(backup(b'a\nb\nc\n'))

    assert summary(job) == (None, None, None, None) and 'not compared' in job.summary_error


def test_workers_volatile_patterns_are_bounded():
    patterns = ['ok', '(unclosed', 'x' * 500, 7, *[f'p{n}' for n in range(100)]]

    kept = _volatile_lines(patterns)

    assert kept[0] == 'ok' and '(unclosed' not in kept and len(kept) <= 50
    assert _volatile_lines('not a list') == []


# --- when summaries are made ------------------------------------------------------


def test_a_stored_job_queues_its_summary(setup, broker, django_capture_on_commit_callbacks):
    job = BackupJob.objects.create(
        device=setup['device'], driver='noop', storage_target=setup['target'], state=BackupJob.COLLECTING
    )

    with django_capture_on_commit_callbacks(execute=True):
        handle_job_event(job_event(setup['collector'], job, EVENT_COLLECTED, sha256='a' * 64, size=1))
        handle_job_event(job_event(setup['storage'], job, EVENT_STORED, sha256='a' * 64, storage_ref='r'))
        handle_job_event(job_event(setup['storage'], job, EVENT_STORED, sha256='a' * 64, storage_ref='r'))

    [(name, [envelope], queue)] = [sent for sent in broker.sent if sent[0] == CHANGE_SUMMARY_TASK]
    assert queue == 'dv.orchestrator' and changes.verified_job_id(envelope) == str(job.id)


def test_the_task_summarises_only_what_the_orchestrator_signed(backup):
    job = backup(b'a\n')
    forged = sign_with({'job_id': str(job.id)}, signing.generate_signing_key())

    change_summary.apply(args=[forged])
    assert summary(job) == (None, None, None, None)

    change_summary.apply(args=[sign_task({'job_id': str(job.id)})])
    assert summary(job) == (True, 1, 0, 0)


def test_the_task_gives_up_on_unreadable_backups_saying_why(backup):
    job = backup(ContentUnavailable('no storage worker answered'))

    change_summary.apply(args=[sign_task({'job_id': str(job.id)})], retries=CHANGE_SUMMARY_RETRIES)

    job.refresh_from_db()
    assert job.changed is None and job.summary_error == 'no storage worker answered'


def test_backfill_queues_backups_without_a_summary(backup, broker):
    backup(b'a\n', hours=1, changed=False)
    pending = backup(b'b\n')

    call_command('summarise_changes')

    [(_, [envelope], _)] = [sent for sent in broker.sent if sent[0] == CHANGE_SUMMARY_TASK]
    assert changes.verified_job_id(envelope) == str(pending.id)


# --- API --------------------------------------------------------------------------


def test_backups_can_be_filtered_by_whether_they_changed(setup, backup, admin_client):
    backup(b'a\n', hours=1, changed=True, lines_added=1, lines_removed=0)
    backup(b'a\n', changed=False, lines_added=0, lines_removed=0)

    changed = admin_client.get('/api/backups/', {'device': setup['device'].pk, 'changed': 'true'}).json()['results']
    everything = admin_client.get('/api/backups/', {'device': setup['device'].pk}).json()['results']

    assert [(job['changed'], job['lines_added'], job['lines_removed']) for job in changed] == [(True, 1, 0)]
    assert len(everything) == 2
