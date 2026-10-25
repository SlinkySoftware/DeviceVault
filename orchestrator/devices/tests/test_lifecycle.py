from datetime import timedelta

import pytest
from django.utils import timezone
from search import indexing
from search.models import SearchDocument

from audit.models import AuditLog
from backups import retention
from backups.jobs import JobError, create_job
from backups.models import BackupJob
from devices import lifecycle
from devices.models import CollectionGroup, Device, DeviceGroup, DeviceType
from devicevault_protocol.names import DELETE_TASK
from devicevault_protocol.push import PUSH_OFF, PUSH_SSH
from policies.models import RetentionPolicy
from push.events import device_problem
from push.service import push_devices
from storage.models import StorageTarget


@pytest.fixture
def broker(monkeypatch):
    """Tasks retention sent, as (name, args, queue)."""
    sent = []
    monkeypatch.setattr(
        'backups.retention.celery_app.send_task',
        lambda name, args=None, queue=None, **kwargs: sent.append((name, args, queue)),
    )
    return sent


@pytest.fixture
def setup(db, worker_keys):
    """A device with a 30-day policy, an approved collector and a storage worker serving a filesystem and a git target."""
    from core import workers

    group = CollectionGroup.objects.create(name='DMZ', rabbitmq_queue_id='dmz')
    workers.approve(
        workers.handle_event(worker_keys('collector-1').event()), role='collector', collection_groups=[group]
    )
    target = StorageTarget.objects.create(name='Local', driver='filesystem', config={'path': 'fs'})
    git = StorageTarget.objects.create(name='History', driver='git', config={'path': 'git'})
    workers.approve(
        workers.handle_event(worker_keys('storage-1').event()), role='storage', storage_targets=[target, git]
    )
    policy = RetentionPolicy.objects.create(name='Month', max_days=30, dry_run=False)
    device = Device.objects.create(
        name='edge-01',
        ip_address='192.0.2.10',
        device_type=DeviceType.objects.create(name='Router'),
        device_group=DeviceGroup.objects.create(name='Core'),
        collection_group=group,
        storage_target=target,
        retention_policy=policy,
        backup_method='noop',
    )
    return {'device': device, 'target': target, 'git': git, 'policy': policy}


@pytest.fixture
def backups(setup):
    """``count`` stored backups of the device, one a day, newest first."""

    def make(count=3, *, target=None, **fields):
        jobs = []
        for day in range(count):
            job = BackupJob.objects.create(
                device=setup['device'],
                state=BackupJob.STORED,
                driver='noop',
                storage_target=target or setup['target'],
                storage_driver=(target or setup['target']).driver,
                storage_ref=f'ref-{day}',
                size_bytes=100,
                **fields,
            )
            BackupJob.objects.filter(pk=job.pk).update(created_at=timezone.now() - timedelta(days=day, hours=1))
            jobs.append(job)
        return jobs

    return make


@pytest.fixture
def group_admin(setup, make_user, client_for):
    return client_for(make_user('operator', grants={setup['device'].device_group: ['admin']}))


def url(device, action=''):
    return f'/api/devices/{device.pk}/{action + "/" if action else ""}'


def retire(device, days_ago=0, **fields):
    """Mark ``device`` inactive ``days_ago`` days ago."""
    Device.objects.filter(pk=device.pk).update(inactive_at=timezone.now() - timedelta(days=days_ago), **fields)
    device.refresh_from_db()
    return device


def prune(jobs):
    BackupJob.objects.filter(pk__in=[job.pk for job in jobs]).update(
        prune_requested_at=timezone.now(), pruned_at=timezone.now()
    )


# --- marking inactive and back ----------------------------------------------------------


def test_marking_inactive_needs_the_group_admin_grant(setup, make_user, client_for):
    viewer = client_for(make_user('viewer', grants={setup['device'].device_group: ['backup_now']}))

    assert viewer.post(url(setup['device'], 'deactivate'), {}, format='json').status_code == 403
    setup['device'].refresh_from_db()
    assert setup['device'].is_active


def test_marking_inactive_starts_the_hold_and_drops_the_search_document(setup, backups, group_admin):
    job = backups(1)[0]
    SearchDocument.objects.create(device=setup['device'], job=job, text='hostname edge-01')

    reply = group_admin.post(url(setup['device'], 'deactivate'), {'reason': 'replaced by edge-02'}, format='json')

    assert reply.status_code == 200, reply.content
    body = reply.json()
    assert (body['lifecycle'], body['inactive_reason'], body['inactive_by_username']) == (
        'inactive',
        'replaced by edge-02',
        'operator',
    )
    setup['device'].refresh_from_db()
    assert body['held_until'] == (setup['device'].inactive_at + timedelta(days=90)).isoformat()
    assert (body['held_backups'], body['held_bytes'], body['can_delete']) == (1, 100, False)
    assert not SearchDocument.objects.exists()
    entry = AuditLog.objects.get(action='device.deactivate')
    assert entry.details['reason'] == 'replaced by edge-02'
    # Twice is a mistake.
    assert group_admin.post(url(setup['device'], 'deactivate'), {}, format='json').status_code == 400


def test_reactivating_clears_the_inactive_and_purge_fields(setup, group_admin):
    retire(setup['device'], inactive_reason='oops', purge_requested_at=timezone.now())

    reply = group_admin.post(url(setup['device'], 'reactivate'), {}, format='json')

    assert reply.status_code == 200, reply.content
    setup['device'].refresh_from_db()
    assert setup['device'].is_active and setup['device'].inactive_reason == ''
    assert setup['device'].purge_requested_at is None
    assert AuditLog.objects.filter(action='device.reactivate').exists()


def test_a_replacement_can_take_the_address_of_an_inactive_device(setup, admin_client):
    retire(setup['device'])
    payload = {
        'name': 'edge-02',
        'ip_address': '192.0.2.10',
        'device_type': setup['device'].device_type_id,
        'device_group': setup['device'].device_group_id,
        'backup_method': 'noop',
    }

    assert admin_client.post('/api/devices/', payload, format='json').status_code == 201
    # Another active device may not.
    duplicate = admin_client.post('/api/devices/', {**payload, 'name': 'edge-03'}, format='json')
    assert duplicate.status_code == 400 and 'ip_address' in duplicate.json()
    # Nor may the old one come back while the replacement holds the address.
    blocked = admin_client.post(url(setup['device'], 'reactivate'), {}, format='json')
    assert blocked.status_code == 400 and 'edge-02' in blocked.json()['error']


def test_an_inactive_device_only_changes_its_policy_and_reason(setup, group_admin):
    retire(setup['device'])
    other = RetentionPolicy.objects.create(name='Year', max_days=365)

    renamed = group_admin.patch(url(setup['device']), {'name': 'renamed'}, format='json')
    allowed = group_admin.patch(
        url(setup['device']), {'retention_policy': other.pk, 'inactive_reason': 'kept for audit'}, format='json'
    )

    assert renamed.status_code == 400 and 'name' in renamed.json()
    assert allowed.status_code == 200, allowed.content
    setup['device'].refresh_from_db()
    assert (setup['device'].retention_policy, setup['device'].inactive_reason) == (other, 'kept for audit')


def test_an_active_device_has_no_reason(setup, group_admin):
    reply = group_admin.patch(url(setup['device']), {'inactive_reason': 'why'}, format='json')

    assert reply.status_code == 400 and 'inactive_reason' in reply.json()


# --- nothing collects an inactive device ------------------------------------------------


def test_an_inactive_device_is_not_backed_up_or_pushed(setup):
    device = retire(setup['device'], push_mode=PUSH_SSH)

    with pytest.raises(JobError, match='inactive'):
        create_job(device)
    assert push_devices() == []
    assert device_problem(device, PUSH_SSH, '192.0.2.10', 'edge-confg') == 'the device is inactive'


def test_push_devices_still_lists_active_pushing_devices(setup):
    Device.objects.filter(pk=setup['device'].pk).update(push_mode=PUSH_SSH)

    assert [d['id'] for d in push_devices()] == [setup['device'].pk]
    Device.objects.filter(pk=setup['device'].pk).update(push_mode=PUSH_OFF)


def test_search_skips_inactive_devices(setup, backups):
    job = backups(1)[0]
    retire(setup['device'])

    assert indexing.stale_jobs() == []
    assert indexing.index_job(job, read=lambda job: b'hostname edge-01') is None
    assert not SearchDocument.objects.exists()


# --- retention ---------------------------------------------------------------------------


def test_during_the_hold_the_policy_applies_as_usual(setup, backups):
    jobs = backups(3)
    device = retire(setup['device'], days_ago=10)
    RetentionPolicy.objects.filter(pk=setup['policy'].pk).update(max_days=1)
    setup['policy'].refresh_from_db()

    # The newest is kept by min_backups; the older two are past max_days.
    assert retention.expired_jobs(device, setup['policy'], timezone.now()) == jobs[1:]


def test_after_the_hold_every_unpinned_backup_expires(setup, backups):
    jobs = backups(3)
    BackupJob.objects.filter(pk=jobs[2].pk).update(pinned=True)
    device = retire(setup['device'], days_ago=91)

    assert retention.expired_jobs(device, setup['policy'], timezone.now()) == jobs[:2]


def test_with_no_hold_limit_backups_are_kept(setup, backups):
    backups(3)
    RetentionPolicy.objects.filter(pk=setup['policy'].pk).update(inactive_keep_days=None)
    setup['policy'].refresh_from_db()
    device = retire(setup['device'], days_ago=1000)

    assert retention.expired_jobs(device, setup['policy'], timezone.now()) == []
    state = lifecycle.lifecycle(device)
    assert state.held_until is None and 'no time limit' in state.refusal()


def test_new_policies_hold_inactive_devices_for_90_days(db):
    assert RetentionPolicy.objects.create(name='New').inactive_keep_days == 90


def test_retention_deletes_an_inactive_device_after_its_hold(
    setup, backups, broker, django_capture_on_commit_callbacks
):
    backups(3)
    retire(setup['device'], days_ago=91)

    with django_capture_on_commit_callbacks(execute=True):
        assert retention.run_retention() == 3
    assert [name for name, _, _ in broker] == [DELETE_TASK]


# --- deleting ----------------------------------------------------------------------------


def test_an_active_device_with_backups_cannot_be_deleted(setup, backups, group_admin):
    backups(1)

    reply = group_admin.delete(url(setup['device']))

    assert reply.status_code == 409 and 'inactive first' in reply.json()['error']
    assert Device.objects.filter(pk=setup['device'].pk).exists()


def test_a_device_that_never_stored_a_backup_can_be_deleted_at_once(setup, group_admin):
    BackupJob.objects.create(
        device=setup['device'], storage_target=setup['target'], driver='noop', state=BackupJob.FAILED
    )

    assert group_admin.get(url(setup['device'])).json()['can_delete']
    reply = group_admin.delete(url(setup['device']))

    assert reply.status_code == 204
    assert not Device.objects.exists() and not BackupJob.objects.exists()
    entry = AuditLog.objects.get(action='device.delete')
    assert (entry.details['device_name'], entry.details['jobs']) == ('edge-01', 1)


@pytest.mark.parametrize(
    ('prepare', 'reason'),
    [
        (lambda setup, jobs: None, 'held until'),
        (lambda setup, jobs: BackupJob.objects.filter(pk=jobs[0].pk).update(pinned=True), 'pinned'),
        (
            lambda setup, jobs: BackupJob.objects.filter(pk=jobs[0].pk).update(prune_requested_at=timezone.now()),
            'waiting for the storage worker',
        ),
    ],
)
def test_an_inactive_device_holding_backups_cannot_be_deleted(setup, backups, group_admin, prepare, reason):
    jobs = backups(2)
    retire(setup['device'])
    prune(jobs[1:])
    prepare(setup, jobs)

    reply = group_admin.delete(url(setup['device']))

    assert reply.status_code == 409 and reason in reply.json()['error']
    assert not AuditLog.objects.filter(action='device.delete').exists()


def test_once_retention_is_done_the_device_is_deleted_with_its_history(setup, backups, group_admin):
    jobs = backups(2)
    git_job = backups(1, target=setup['git'])[0]
    retire(setup['device'], days_ago=100)
    prune(jobs)

    listed = group_admin.get('/api/devices/?lifecycle=deletable').json()
    assert [row['id'] for row in listed] == [setup['device'].pk] and listed[0]['can_delete']
    reply = group_admin.delete(url(setup['device']))

    assert reply.status_code == 204
    assert not BackupJob.objects.filter(pk=git_job.pk).exists()
    snapshot = AuditLog.objects.get(action='device.delete').details
    assert snapshot['jobs'] == 3 and snapshot['targets_keeping_content'] == ['History']


def test_the_list_filters_by_lifecycle(setup, backups, admin_client):
    backups(1)
    spare = Device.objects.create(
        name='spare', ip_address='192.0.2.11', device_type=setup['device'].device_type, inactive_at=timezone.now()
    )
    retire(setup['device'])

    def names(state):
        return [row['name'] for row in admin_client.get(f'/api/devices/?lifecycle={state}').json()]

    assert (names('active'), names('inactive'), names('deletable')) == ([], ['edge-01'], ['spare'])
    assert admin_client.get('/api/devices/?lifecycle=gone').status_code == 400
    assert spare.pk in [row['id'] for row in admin_client.get('/api/devices/').json()]


# --- purging -----------------------------------------------------------------------------


def test_purging_is_for_global_administrators(setup, backups, group_admin):
    backups(1)
    retire(setup['device'])

    assert group_admin.post(url(setup['device'], 'purge'), {'confirm': 'edge-01'}, format='json').status_code == 403


def test_purging_needs_the_name_and_an_inactive_device(setup, backups, admin_client):
    backups(1)

    active = admin_client.post(url(setup['device'], 'purge'), {'confirm': 'edge-01'}, format='json')
    retire(setup['device'])
    unconfirmed = admin_client.post(url(setup['device'], 'purge'), {'confirm': 'edge'}, format='json')

    assert active.status_code == 400 and 'inactive' in active.json()['error']
    assert unconfirmed.status_code == 400 and 'name' in unconfirmed.json()['error']
    assert not BackupJob.objects.filter(prune_requested_at__isnull=False).exists()


def test_purging_unpins_and_deletes_every_backup_at_once(
    setup, backups, admin_client, broker, make_user, django_capture_on_commit_callbacks
):
    jobs = backups(3)
    pinner = make_user('pinner')
    BackupJob.objects.filter(pk=jobs[0].pk).update(pinned=True, pinned_by=pinner, label='baseline')
    retire(setup['device'])

    with django_capture_on_commit_callbacks(execute=True):
        reply = admin_client.post(url(setup['device'], 'purge'), {'confirm': 'edge-01'}, format='json')

    assert reply.status_code == 200, reply.content
    assert reply.json()['purge_requested_by_username'] == 'admin'
    assert BackupJob.objects.filter(prune_requested_at__isnull=False).count() == 3
    assert not BackupJob.objects.filter(pinned=True).exists()
    assert [name for name, _, _ in broker] == [DELETE_TASK]
    entry = AuditLog.objects.get(action='device.purge')
    assert entry.details['requested'] == 3
    assert entry.details['unpinned'] == [{'job': str(jobs[0].pk), 'label': 'baseline', 'pinned_by': 'pinner'}]
    # Nobody pins it back.
    pin = admin_client.post(f'/api/backups/{jobs[0].pk}/pin/', {'pinned': True}, format='json')
    assert pin.status_code == 400


def test_retention_sends_what_a_purge_could_not_even_in_dry_run(setup, backups, broker):
    backups(2)
    RetentionPolicy.objects.filter(pk=setup['policy'].pk).update(dry_run=True)
    retire(setup['device'], purge_requested_at=timezone.now())

    assert retention.run_retention() == 2
    assert AuditLog.objects.get(action='retention.purge').details['requested'] == 2
    # The policy's own pass leaves the purged device to the purge.
    assert retention.plan(RetentionPolicy.objects.get()).jobs == []
