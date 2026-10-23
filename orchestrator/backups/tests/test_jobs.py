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
    assert task['device'] == {'id': setup['device'].id, 'name': 'Edge 01', 'address': '192.0.2.10'}
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
    assert expire_stale_jobs() == 0
