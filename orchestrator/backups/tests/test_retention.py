from datetime import timedelta

import pytest
from django.utils import timezone

from audit.models import AuditLog
from backups import retention, scheduler
from backups.content import ContentUnavailable, read_raw
from backups.jobs import handle_job_event
from backups.models import BackupJob
from backups.tests.conftest import job_event
from core.models import Worker
from core.signing import public_key
from devicevault_protocol import signing
from devicevault_protocol.jobs import EVENT_DELETE_FAILED, EVENT_DELETED
from devicevault_protocol.tasks import verify_task
from policies.models import RetentionPolicy
from storage.models import StorageTarget

NOW = timezone.now()
ORCHESTRATOR = lambda: signing.public_key_from_b64(public_key())  # noqa: E731


@pytest.fixture
def broker(monkeypatch):
    sent = []
    monkeypatch.setattr(
        'backups.retention.celery_app.send_task',
        lambda name, args=None, queue=None, **kwargs: sent.append((name, args, queue)),
    )
    return sent


@pytest.fixture
def backups(setup):
    """Ten stored backups of the device, one a day, newest first, 100 bytes each."""

    def make(count=10, *, device=None, target=None, **fields):
        jobs = []
        for day in range(count):
            job = BackupJob.objects.create(
                device=device or setup['device'],
                state=BackupJob.STORED,
                driver='noop',
                storage_target=target or setup['target'],
                storage_driver='filesystem',
                storage_ref=f'ref-{day}',
                stored_sha256='a' * 64,
                size_bytes=100,
                **fields,
            )
            BackupJob.objects.filter(pk=job.pk).update(created_at=NOW - timedelta(days=day, hours=1))
            job.refresh_from_db()
            jobs.append(job)
        return jobs

    return make


def policy_for(setup, **limits):
    policy = RetentionPolicy.objects.create(name='Policy', **{'dry_run': False, **limits})
    setup['device'].retention_policy = policy
    setup['device'].save()
    return policy


def expired(setup, policy):
    return [job.storage_ref for job in retention.expired_jobs(setup['device'], policy, NOW)]


# --- which backups expire ---------------------------------------------------------


@pytest.mark.parametrize(
    ('limits', 'gone'),
    [
        ({'max_backups': 7}, ['ref-7', 'ref-8', 'ref-9']),
        ({'max_days': 8}, ['ref-8', 'ref-9']),
        ({'max_size_bytes': 850}, ['ref-8', 'ref-9']),
        # Any limit that is set applies.
        ({'max_backups': 9, 'max_days': 7}, ['ref-7', 'ref-8', 'ref-9']),
        ({}, []),
    ],
)
def test_backups_expire_when_any_limit_says_so(setup, backups, limits, gone):
    backups()
    assert expired(setup, policy_for(setup, **limits)) == gone


def test_the_newest_backups_are_always_kept(setup, backups):
    backups()

    assert expired(setup, policy_for(setup, max_days=0)) == [f'ref-{day}' for day in range(1, 10)]
    assert expired(setup, policy_for(setup, max_backups=0, min_backups=4)) == [f'ref-{d}' for d in range(4, 10)]


def test_pinned_backups_are_neither_counted_nor_deleted(setup, backups):
    jobs = backups()
    BackupJob.objects.filter(pk__in=[jobs[0].pk, jobs[8].pk]).update(pinned=True)

    # ref-0 is pinned, so the newest two unpinned ones are ref-1 and ref-2.
    assert expired(setup, policy_for(setup, max_backups=2)) == ['ref-3', 'ref-4', 'ref-5', 'ref-6', 'ref-7', 'ref-9']


def test_only_stored_backups_that_are_still_there_count(setup, backups):
    jobs = backups(4)
    BackupJob.objects.filter(pk=jobs[0].pk).update(state=BackupJob.FAILED)
    BackupJob.objects.filter(pk=jobs[1].pk).update(pruned_at=NOW)

    assert expired(setup, policy_for(setup, max_backups=1)) == ['ref-3']


# --- retention passes -------------------------------------------------------------


def test_a_dry_run_audits_what_would_go_once_and_deletes_nothing(setup, backups, broker):
    backups()
    policy = policy_for(setup, max_backups=7, dry_run=True)

    retention.run_retention(NOW)
    retention.run_retention(NOW)

    assert broker == []
    assert not BackupJob.objects.filter(prune_requested_at__isnull=False).exists()
    [entry] = AuditLog.objects.filter(action='retention.dry_run')
    assert entry.actor_name == 'retention' and entry.details['expired'] == 3
    assert entry.details['devices'] == [{'device': setup['device'].pk, 'device_name': 'Edge 01', 'backups': 3}]
    policy.refresh_from_db()
    assert policy.last_run_at == NOW and policy.last_result['expired_bytes'] == 300


def test_an_enforced_policy_sends_signed_deletions_to_the_target(
    setup, backups, broker, django_capture_on_commit_callbacks
):
    backups()
    policy_for(setup, max_backups=7)

    with django_capture_on_commit_callbacks(execute=True):
        assert retention.run_retention(NOW) == 3

    [(name, [envelope], queue)] = broker
    assert (name, queue) == ('storage.delete', setup['target'].queue)
    task = verify_task(envelope, ORCHESTRATOR())
    assert task['target'] == {'id': str(setup['target'].id), 'driver': 'filesystem'}
    assert task['config'] == {'path': 'fs'}
    assert [item['storage_ref'] for item in task['items']] == ['ref-7', 'ref-8', 'ref-9']
    assert BackupJob.objects.filter(prune_requested_at=NOW).count() == 3
    [entry] = AuditLog.objects.filter(action='retention.delete')
    assert entry.details['requested'] == 3 and entry.details['requested_bytes'] == 300


def test_deletions_are_asked_for_again_only_once_overdue(setup, backups, broker, django_capture_on_commit_callbacks):
    backups()
    policy_for(setup, max_backups=9)

    with django_capture_on_commit_callbacks(execute=True):
        retention.run_retention(NOW)
        retention.run_retention(NOW + timedelta(hours=1))
        retention.run_retention(NOW + retention.PRUNE_RETRY_AFTER + timedelta(hours=1))

    assert len(broker) == 2


def test_a_backup_being_deleted_cannot_be_read(setup, backups, broker):
    [job] = backups(1)
    BackupJob.objects.filter(pk=job.pk).update(prune_requested_at=NOW)
    job.refresh_from_db()

    with pytest.raises(ContentUnavailable, match='retention'):
        read_raw(job)


def test_targets_whose_driver_keeps_everything_are_left_alone(setup, backups, broker):
    git = StorageTarget.objects.create(name='Git', driver='git', config={'path': 'git'})
    git.workers.set(setup['target'].workers.all())
    backups(target=git)
    policy = policy_for(setup, max_backups=7)

    assert retention.run_retention(NOW) == 0

    assert broker == []
    policy.refresh_from_db()
    assert policy.last_result['kept_undeletable'] == 3


def test_backups_on_a_target_no_worker_serves_wait_for_one(setup, backups, broker):
    backups()
    # Offline or revoked: no approved storage worker, so no driver catalogue either.
    Worker.objects.filter(role='storage').update(status='revoked')
    policy = policy_for(setup, max_backups=7)

    assert retention.run_retention(NOW) == 0

    assert broker == []
    policy.refresh_from_db()
    assert (policy.last_result['expired'], policy.last_result['kept_undeletable']) == (3, 0)
    assert not BackupJob.objects.filter(prune_requested_at__isnull=False).exists()


def test_a_backup_pinned_while_planning_is_not_deleted(setup, backups, broker, django_capture_on_commit_callbacks):
    jobs = backups()
    planned = retention.expired_jobs(setup['device'], policy_for(setup, max_backups=8), NOW)
    BackupJob.objects.filter(pk=jobs[9].pk).update(pinned=True)

    with django_capture_on_commit_callbacks(execute=True):
        sent = retention.request_deletion(planned, NOW)

    assert [job.storage_ref for job in sent] == ['ref-8']


def test_each_pass_has_a_deletion_budget(setup, backups, broker, monkeypatch, django_capture_on_commit_callbacks):
    monkeypatch.setattr(retention, 'MAX_DELETIONS_PER_PASS', 2)
    monkeypatch.setattr(retention, 'ITEMS_PER_TASK', 1)
    backups()
    policy_for(setup, max_backups=1)

    with django_capture_on_commit_callbacks(execute=True):
        assert retention.run_retention(NOW) == 2

    assert len(broker) == 2


def test_the_scheduler_applies_retention_at_its_interval(setup, backups, broker, settings, monkeypatch):
    settings.DEVICEVAULT_RETENTION_INTERVAL_MIN = 60
    monkeypatch.setattr(scheduler, '_last_retention', None)
    backups()
    policy = policy_for(setup, max_backups=1, dry_run=True)

    scheduler.apply_retention(NOW)
    first = RetentionPolicy.objects.get(pk=policy.pk).last_run_at
    assert scheduler.apply_retention(NOW + timedelta(minutes=30)) is None
    scheduler.apply_retention(NOW + timedelta(minutes=61))

    assert first == NOW
    assert RetentionPolicy.objects.get(pk=policy.pk).last_run_at == NOW + timedelta(minutes=61)


# --- the storage worker's reports -------------------------------------------------


@pytest.fixture
def pending(setup, backups):
    [job] = backups(1)
    BackupJob.objects.filter(pk=job.pk).update(prune_requested_at=NOW)
    job.refresh_from_db()
    return job


def test_a_confirmed_deletion_marks_the_backup_pruned(setup, pending):
    entry = {'source': 'storage', 'timestamp': NOW.isoformat(), 'severity': 'INFO', 'message': 'deleted'}

    job = handle_job_event(job_event(setup['storage'], pending, EVENT_DELETED, log=[entry]))

    assert job.pruned_at is not None and job.state == BackupJob.STORED
    assert job.log[-1]['message'] == 'deleted'


def test_a_failed_deletion_leaves_the_backup_for_a_later_pass(setup, pending):
    job = handle_job_event(job_event(setup['storage'], pending, EVENT_DELETE_FAILED, error='disk on fire'))

    assert job.prune_requested_at is None and job.pruned_at is None
    assert 'disk on fire' in job.log[-1]['message']


def test_deletion_reports_need_a_requested_deletion_and_the_targets_worker(setup, backups, pending):
    # From a collector: not one of the target's workers.
    job = handle_job_event(job_event(setup['collector'], pending, EVENT_DELETED))
    assert job.pruned_at is None

    # For a backup nobody asked to delete.
    [kept] = backups(1)
    job = handle_job_event(job_event(setup['storage'], kept, EVENT_DELETED))
    assert job.pruned_at is None


# --- API --------------------------------------------------------------------------


def test_the_preview_shows_what_a_policy_expires(setup, backups, admin_client):
    backups()
    policy = policy_for(setup, max_backups=7)

    reply = admin_client.get(f'/api/retention-policies/{policy.pk}/preview/')

    assert reply.status_code == 200
    body = reply.json()
    assert (body['expired'], body['expired_bytes'], body['kept_undeletable']) == (3, 300, 0)
    [device] = body['devices']
    assert (device['device_name'], device['backups'], device['bytes']) == ('Edge 01', 3, 300)
    assert not BackupJob.objects.filter(prune_requested_at__isnull=False).exists()


def test_only_global_administrators_preview_or_change_policies(setup, make_user, client_for):
    policy = policy_for(setup, max_backups=7)
    member = client_for(make_user('member', grants={setup['device'].device_group: ('admin',)}))

    assert member.get(f'/api/retention-policies/{policy.pk}/').status_code == 200
    assert member.get(f'/api/retention-policies/{policy.pk}/preview/').status_code == 403
    assert member.patch(f'/api/retention-policies/{policy.pk}/', {'dry_run': True}).status_code == 403


def test_policy_changes_are_audited(setup, admin_client):
    policy = policy_for(setup, max_backups=7)

    reply = admin_client.patch(
        f'/api/retention-policies/{policy.pk}/', {'dry_run': True, 'last_run_at': NOW.isoformat()}, format='json'
    )

    assert reply.status_code == 200 and reply.json()['last_run_at'] is None
    [entry] = AuditLog.objects.filter(action='retention_policy.update')
    assert entry.details == {'policy': 'Policy', 'dry_run': True}


def test_min_backups_is_at_least_one(admin_client, db):
    reply = admin_client.post('/api/retention-policies/', {'name': 'Bad', 'min_backups': 0}, format='json')

    assert reply.status_code == 400 and 'min_backups' in reply.json()


def test_jobs_show_whether_retention_deleted_them(setup, pending, admin_client):
    [job] = admin_client.get('/api/backups/', {'device': setup['device'].pk}).json()['results']

    assert job['pruned'] is True and job['pinned'] is False


def test_a_deleted_backups_content_is_gone(setup, pending, admin_client):
    reply = admin_client.get(f'/api/backups/{pending.id}/content/')

    assert reply.status_code == 410 and 'retention' in reply.json()['error']
