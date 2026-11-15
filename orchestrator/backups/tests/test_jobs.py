from datetime import timedelta

import pytest
from django.utils import timezone

from backups.jobs import EventRejected, JobError, create_job, expire_stale_jobs, handle_job_event
from backups.models import BackupJob
from backups.tests.conftest import job_event
from core.signing import public_key
from devicevault_protocol import signing
from devicevault_protocol.jobs import EVENT_COLLECTED, EVENT_FAILED, EVENT_STARTED, EVENT_STORED, STAGE_STORE
from devicevault_protocol.tasks import verify_task

ORCHESTRATOR = lambda: signing.public_key_from_b64(public_key())  # noqa: E731
SHA = 'a' * 64


def queue_job(setup, django_capture_on_commit_callbacks, **kwargs):
    with django_capture_on_commit_callbacks(execute=True):
        return create_job(setup['device'], **kwargs)


def test_a_job_is_dispatched_as_signed_tasks_for_collector_and_storage(
    setup, broker, django_capture_on_commit_callbacks
):
    job, created = queue_job(setup, django_capture_on_commit_callbacks)

    assert created and job.state == BackupJob.QUEUED
    [(name, [envelope], queue)] = broker.sent
    assert (name, queue) == ('job.collect', 'collector.group.dmz')
    task = verify_task(envelope, ORCHESTRATOR())
    assert task['job_id'] == str(job.id)
    assert task['device'] == {'id': setup['device'].id, 'name': 'Edge 01', 'address': '192.0.2.10', 'host_key': None}
    assert task['store']['queue'] == f'storage.target.{setup["target"].id}'
    store = verify_task(task['store']['envelope'], ORCHESTRATOR())
    assert store['config'] == {'path': 'fs'} and store['target']['driver'] == 'filesystem'
    assert store['name']['device_key'] == f'{setup["device"].id}-edge-01'


def test_an_active_job_is_reused_instead_of_queueing_another(setup, broker, django_capture_on_commit_callbacks):
    first, _ = queue_job(setup, django_capture_on_commit_callbacks)
    second, created = queue_job(setup, django_capture_on_commit_callbacks)

    assert second == first and not created
    assert len(broker.sent) == 1


@pytest.mark.parametrize(
    ('change', 'message'),
    [
        ({'collection_group': None}, 'no collection group'),
        ({'storage_target': None}, 'no storage target'),
    ],
)
def test_devices_that_cannot_be_backed_up_are_refused(setup, broker, change, message):
    for field, value in change.items():
        setattr(setup['device'], field, value)

    with pytest.raises(JobError, match=message):
        create_job(setup['device'])


def test_devices_need_workers_on_both_sides(setup, broker):
    setup['target'].workers.clear()

    with pytest.raises(JobError, match='has no approved storage worker'):
        create_job(setup['device'])

    setup['group'].workers.clear()
    with pytest.raises(JobError, match='no approved collector'):
        create_job(setup['device'])


def collected(setup, job, sha=SHA):
    return handle_job_event(
        job_event(setup['collector'], job, EVENT_COLLECTED, sha256=sha, size=10, is_binary=False, duration_ms=5)
    )


def stored(setup, job, sha=SHA):
    return handle_job_event(job_event(setup['storage'], job, EVENT_STORED, sha256=sha, storage_ref='ref'))


def test_a_job_is_stored_when_both_sides_agree_on_the_hash(setup, broker):
    job, _ = create_job(setup['device'])
    handle_job_event(job_event(setup['collector'], job, EVENT_STARTED, attempt=1, log=[{'message': 'hi'}]))
    assert BackupJob.objects.get(pk=job.pk).state == BackupJob.COLLECTING

    assert collected(setup, job).state == BackupJob.COLLECTED
    handle_job_event(job_event(setup['storage'], job, EVENT_STARTED, stage=STAGE_STORE))
    job = stored(setup, job)

    assert job.state == BackupJob.STORED
    assert (job.collector, job.storage_worker, job.storage_ref) == ('collector-1', 'storage-1', 'ref')
    assert job.log == [{'message': 'hi'}]
    setup['device'].refresh_from_db()
    assert setup['device'].last_backup_status == 'success'


def test_storage_may_report_before_the_collector(setup, broker):
    job, _ = create_job(setup['device'])

    assert stored(setup, job).state == BackupJob.STORING
    assert collected(setup, job).state == BackupJob.STORED


def test_a_hash_mismatch_fails_the_job(setup, broker):
    job, _ = create_job(setup['device'])
    collected(setup, job)

    job = stored(setup, job, sha='b' * 64)

    assert job.state == BackupJob.FAILED
    assert 'does not match' in job.error
    setup['device'].refresh_from_db()
    assert setup['device'].last_backup_status == 'failure'


def test_late_events_do_not_reopen_a_finished_job(setup, broker):
    job, _ = create_job(setup['device'])
    handle_job_event(job_event(setup['collector'], job, EVENT_FAILED, error='auth failed'))

    job = collected(setup, job)

    assert job.state == BackupJob.FAILED and job.error == 'auth failed'


def test_events_from_unapproved_or_impersonated_workers_are_rejected(setup, broker, worker_keys):
    from core import workers

    job, _ = create_job(setup['device'])
    pending = worker_keys('pending')
    workers.handle_event(pending.event())
    impostor = setup['collector'].__class__('impostor')
    impostor.id = setup['collector'].id  # claims to be the collector, with another key

    for keys in (pending, impostor):
        with pytest.raises(EventRejected):
            handle_job_event(job_event(keys, job, EVENT_FAILED, error='x'))

    assert BackupJob.objects.get(pk=job.pk).state == BackupJob.QUEUED


def test_stale_jobs_time_out(setup, broker, settings):
    job, _ = create_job(setup['device'])
    BackupJob.objects.filter(pk=job.pk).update(created_at=timezone.now() - timedelta(minutes=121))

    assert expire_stale_jobs() == 1

    job.refresh_from_db()
    assert job.state == BackupJob.TIMED_OUT
    assert job.failure_reason == BackupJob.REASON_ORPHANED
    assert expire_stale_jobs() == 0


# --- failure reasons -----------------------------------------------------------------


def test_a_stored_job_has_no_failure_reason(setup, broker):
    job, _ = create_job(setup['device'])
    collected(setup, job)

    job = stored(setup, job)

    assert job.state == BackupJob.STORED and job.failure_reason is None


@pytest.mark.parametrize(
    ('reported', 'expected'),
    [
        ('connection', 'connection'),
        ('auth', 'auth'),
        ('timeout', 'timeout'),
        ('command', 'command'),
        ('disk on fire', 'unknown'),
        (None, 'unknown'),
        (7, 'unknown'),
    ],
)
def test_the_collectors_failure_reason_is_recorded(setup, broker, reported, expected):
    job, _ = create_job(setup['device'])
    details = {'error': 'it broke', 'stage': 'collect'}
    if reported is not None:
        details['reason'] = reported

    job = handle_job_event(job_event(setup['collector'], job, EVENT_FAILED, **details))

    assert job.state == BackupJob.FAILED
    assert (job.failure_reason, job.error) == (expected, 'it broke')
    assert BackupJob.objects.get(pk=job.pk).failure_reason == expected


@pytest.mark.parametrize(
    ('reported', 'expected'),
    [('storage', 'storage'), ('integrity', 'integrity'), ('auth', 'storage'), (None, 'storage')],
)
def test_storage_step_failures_are_storage_unless_the_hash_differed(setup, broker, reported, expected):
    job, _ = create_job(setup['device'])
    collected(setup, job)
    details = {'error': 'disk full', 'stage': STAGE_STORE}
    if reported is not None:
        details['reason'] = reported

    job = handle_job_event(job_event(setup['storage'], job, EVENT_FAILED, **details))

    assert job.failure_reason == expected


def test_a_hash_mismatch_is_an_integrity_failure(setup, broker):
    job, _ = create_job(setup['device'])
    collected(setup, job)

    job = stored(setup, job, sha='b' * 64)

    assert job.failure_reason == BackupJob.REASON_INTEGRITY


def test_a_timed_out_job_that_completes_after_all_loses_its_reason(setup, broker):
    job, _ = create_job(setup['device'])
    BackupJob.objects.filter(pk=job.pk).update(created_at=timezone.now() - timedelta(minutes=121))
    expire_stale_jobs()

    collected(setup, job)
    job = stored(setup, job)

    assert job.state == BackupJob.STORED and job.failure_reason is None


def test_failure_reason_is_read_only_in_the_api():
    from backups.api import BackupJobSerializer

    assert 'failure_reason' in BackupJobSerializer.Meta.fields
    assert 'failure_reason' in BackupJobSerializer.Meta.read_only_fields


# --- SSH host keys (pinned on first use) ----------------------------------------------------------

HOST_KEY = 'ssh-ed25519 AAAAC3NzaC1lZDI1NTE5AAAAIJ/5z9AzdT8Dm9DM5cwhVsGr+7YDGjr3iqkJqscQWMlL'
OTHER_KEY = 'ssh-ed25519 AAAAC3NzaC1lZDI1NTE5AAAAILDOn0OvFfw6p/WXBHAsaPNJxLtOnAjNRemDF7b3iKed'


def collected_with_key(setup, job, key, keys=None):
    event = job_event(keys or setup['collector'], job, EVENT_COLLECTED, sha256=SHA, size=10, host_key=key)
    return handle_job_event(event)


def test_the_first_collected_backup_pins_the_devices_host_key(setup, broker):
    from audit.models import AuditLog

    job, _ = create_job(setup['device'])

    job = collected_with_key(setup, job, HOST_KEY)

    device = setup['device']
    device.refresh_from_db()
    assert device.ssh_host_key == HOST_KEY and device.ssh_host_key_pinned_at is not None
    assert device.ssh_host_key_fingerprint.startswith('SHA256:') and device.ssh_host_key_type == 'ssh-ed25519'
    assert device.ssh_host_key_fingerprint in job.log[-1]['message']
    entry = AuditLog.objects.get(action='device.host_key_pin')
    assert entry.actor_name == 'collector-1' and entry.details['fingerprint'] == device.ssh_host_key_fingerprint


def test_the_pinned_host_key_travels_in_the_signed_collect_task(setup, broker, django_capture_on_commit_callbacks):
    setup['device'].ssh_host_key = HOST_KEY
    setup['device'].save()

    queue_job(setup, django_capture_on_commit_callbacks)

    [(_, [envelope], _)] = broker.sent
    assert verify_task(envelope, ORCHESTRATOR())['device']['host_key'] == HOST_KEY


def test_a_pinned_host_key_is_never_replaced_by_an_event(setup, broker):
    setup['device'].ssh_host_key = HOST_KEY
    setup['device'].save()
    job, _ = create_job(setup['device'])

    collected_with_key(setup, job, OTHER_KEY)

    setup['device'].refresh_from_db()
    assert setup['device'].ssh_host_key == HOST_KEY


def test_only_the_devices_own_collectors_can_pin_its_host_key(setup, broker, worker_keys):
    from core import workers
    from devices.models import CollectionGroup

    elsewhere = worker_keys('collector-2')
    other_group = CollectionGroup.objects.create(name='Lab', rabbitmq_queue_id='lab')
    workers.approve(workers.handle_event(elsewhere.event()), role='collector', collection_groups=[other_group])
    job, _ = create_job(setup['device'])

    collected_with_key(setup, job, HOST_KEY, keys=elsewhere)
    collected_with_key(setup, job, HOST_KEY, keys=setup['storage'])

    setup['device'].refresh_from_db()
    assert setup['device'].ssh_host_key == ''


@pytest.mark.parametrize('key', ['ssh-ed25519', 'ssh-ed25519 not base64!', 'ssh-ed25519 AAAAC3NzaC1lZDI1NTE5AAAAI', 7])
def test_malformed_host_keys_are_not_pinned(setup, broker, key):
    job, _ = create_job(setup['device'])

    assert collected_with_key(setup, job, key).state == BackupJob.COLLECTED

    setup['device'].refresh_from_db()
    assert setup['device'].ssh_host_key == ''


# --- events are accepted only from the job's own workers -----------------------------------------


@pytest.fixture
def outsiders(setup, worker_keys):
    """Approved workers with no part in the device's backups: a collector of another group, a storage
    worker of another target, and a receiver."""
    from core import workers
    from devices.models import CollectionGroup
    from storage.models import StorageTarget

    collector, storage, receiver = (worker_keys(name) for name in ('collector-lab', 'storage-lab', 'receiver-1'))
    lab = CollectionGroup.objects.create(name='Lab', rabbitmq_queue_id='lab')
    workers.approve(workers.handle_event(collector.event()), role='collector', collection_groups=[lab])
    target = StorageTarget.objects.create(name='Lab store', driver='filesystem', config={'path': 'lab'})
    workers.approve(workers.handle_event(storage.event()), role='storage', storage_targets=[target])
    workers.approve(workers.handle_event(receiver.event()), role='receiver')
    return {'collector': collector, 'storage': storage, 'receiver': receiver}


def unchanged(job):
    fresh = BackupJob.objects.get(pk=job.pk)
    return (fresh.state, fresh.log, fresh.error, fresh.collected_sha256, fresh.stored_sha256, fresh.storage_ref)


@pytest.mark.parametrize('who', ['collector', 'storage', 'receiver'])
@pytest.mark.parametrize(
    'event',
    [
        {'event': EVENT_STARTED, 'attempt': 1},
        {'event': EVENT_COLLECTED, 'sha256': SHA, 'size': 10},
        {'event': EVENT_STORED, 'sha256': SHA, 'storage_ref': 'elsewhere'},
        {'event': EVENT_STARTED, 'stage': STAGE_STORE},
        {'event': EVENT_FAILED, 'error': 'forged'},
        {'event': EVENT_FAILED, 'stage': STAGE_STORE, 'error': 'forged'},
        {'event': 'made-up'},
    ],
)
def test_workers_with_no_part_in_a_job_cannot_report_on_it(setup, broker, outsiders, who, event):
    job, _ = create_job(setup['device'])
    before = unchanged(job)
    details = {key: value for key, value in event.items() if key != 'event'}

    handle_job_event(job_event(outsiders[who], job, event['event'], log=[{'message': 'forged'}], **details))

    assert unchanged(job) == before
    setup['device'].refresh_from_db()
    assert setup['device'].last_backup_status == ''


def test_each_of_a_jobs_workers_reports_only_its_own_step(setup, broker):
    job, _ = create_job(setup['device'])
    before = unchanged(job)

    # The collector cannot report the storing step, nor the storage worker the collecting one.
    handle_job_event(job_event(setup['collector'], job, EVENT_STORED, sha256=SHA, storage_ref='ref'))
    handle_job_event(job_event(setup['collector'], job, EVENT_FAILED, stage=STAGE_STORE, error='forged'))
    handle_job_event(job_event(setup['storage'], job, EVENT_COLLECTED, sha256=SHA, size=10))
    handle_job_event(job_event(setup['storage'], job, EVENT_FAILED, error='forged'))

    assert unchanged(job) == before


def test_a_finished_jobs_log_is_closed_to_other_workers(setup, broker, outsiders):
    job, _ = create_job(setup['device'])
    collected(setup, job)
    job = stored(setup, job)
    before = unchanged(job)

    handle_job_event(job_event(outsiders['collector'], job, EVENT_STARTED, log=[{'message': 'forged'}]))

    assert unchanged(job) == before


def test_a_worker_taken_off_the_job_loses_its_say(setup, broker):
    job, _ = create_job(setup['device'])
    setup['group'].workers.clear()
    setup['target'].workers.clear()

    collected(setup, job)
    stored(setup, job)

    assert BackupJob.objects.get(pk=job.pk).state == BackupJob.QUEUED


def test_no_worker_reports_the_collection_of_a_pushed_backup(setup, broker):
    job = BackupJob.objects.create(
        device=setup['device'],
        state=BackupJob.COLLECTED,
        trigger=BackupJob.TRIGGER_PUSH,
        storage_target=setup['target'],
        collected_sha256=SHA,
    )

    handle_job_event(job_event(setup['collector'], job, EVENT_COLLECTED, sha256='b' * 64, size=10))
    handle_job_event(job_event(setup['collector'], job, EVENT_FAILED, error='forged'))
    assert BackupJob.objects.get(pk=job.pk).collected_sha256 == SHA

    # Its storage step is still the storage worker's to report.
    assert stored(setup, job).state == BackupJob.STORED
