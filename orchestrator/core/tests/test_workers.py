import pytest
from django.contrib.auth.models import User
from rest_framework.test import APIClient

from core import workers
from core.models import Worker
from core.signing import public_key
from devices.models import CollectionGroup
from devicevault_protocol import signing
from devicevault_protocol.registration import STATUS_APPROVED, STATUS_PENDING, STATUS_REVOKED

ORCHESTRATOR = lambda: signing.public_key_from_b64(public_key())  # noqa: E731


def assignments(published, worker):
    """Verified assignment payloads sent to ``worker``."""
    return [signing.verify(env, ORCHESTRATOR()) for wid, env in published if wid == str(worker.id)]


# --- registration -----------------------------------------------------------------


def test_first_event_registers_a_pending_worker_and_sends_nothing(db, worker_keys, published):
    keys = worker_keys('collector-1')

    worker = workers.handle_event(keys.event())

    assert worker.status == STATUS_PENDING
    assert worker.name == 'collector-1'
    assert worker.fingerprint == signing.fingerprint(signing.public_key_to_b64(keys.key))
    assert published == []


def test_a_worker_id_cannot_be_taken_over_with_another_key(db, worker_keys):
    keys = worker_keys()
    workers.handle_event(keys.event())
    impostor = worker_keys()
    impostor.id = keys.id

    with pytest.raises(workers.EventRejected):
        workers.handle_event(impostor.event(name='evil'))
    assert Worker.objects.get(pk=keys.id).name == 'collector-1'


def test_events_must_be_signed_by_the_worker_they_describe(db, worker_keys):
    keys = worker_keys()
    envelope = keys.event()
    envelope['payload']['name'] = 'tampered'

    with pytest.raises(workers.EventRejected):
        workers.handle_event(envelope)
    assert not Worker.objects.exists()


# --- assignment -------------------------------------------------------------------


def test_approval_pushes_a_signed_assignment_with_the_group_queues(db, worker_keys, published):
    group = CollectionGroup.objects.create(name='DMZ', rabbitmq_queue_id='dmz')
    worker = workers.handle_event(worker_keys().event())

    workers.approve(worker, role='collector', collection_groups=[group])

    [payload] = assignments(published, worker)
    assert payload == {
        'type': 'assignment',
        'worker_id': str(worker.id),
        'version': 1,
        'status': STATUS_APPROVED,
        'role': 'collector',
        'queues': ['collector.group.dmz'],
        'orchestrator_key': public_key(),
    }


def test_heartbeats_reconcile_until_the_worker_reports_the_current_version(db, worker_keys, published):
    keys = worker_keys()
    worker = workers.approve(workers.handle_event(keys.event()), role='collector')
    published.clear()

    workers.handle_event(keys.event(applied_version=0))  # e.g. restarted, lost its assignment
    assert len(assignments(published, worker)) == 1

    published.clear()
    workers.handle_event(keys.event(applied_version=1))
    assert published == []


def test_a_forgotten_worker_is_reapproved_with_a_newer_version(db, worker_keys, published):
    keys = worker_keys('storage-1')
    worker = workers.approve(workers.handle_event(keys.event()), role='storage')
    workers.revoke(worker)  # version 2, which the worker applies
    Worker.objects.filter(pk=keys.id).delete()

    again = workers.handle_event(keys.event(applied_version=2))
    workers.approve(again, role='storage')

    assert assignments(published, again)[-1]['version'] == 3


def test_a_worker_ahead_of_the_database_gets_a_newer_assignment(db, worker_keys, published):
    keys = worker_keys()
    worker = workers.approve(workers.handle_event(keys.event()), role='collector')
    published.clear()

    workers.handle_event(keys.event(applied_version=7))  # e.g. the database was restored

    assert [p['version'] for p in assignments(published, worker)] == [8]


def test_revocation_sends_an_empty_assignment(db, worker_keys, published):
    worker = workers.approve(workers.handle_event(worker_keys().event()), role='storage')

    workers.revoke(worker)

    last = assignments(published, worker)[-1]
    assert (last['status'], last['queues'], last['version']) == (STATUS_REVOKED, [], 2)


def test_renaming_a_group_queue_reassigns_its_collectors(db, approved_collector, published):
    group = CollectionGroup.objects.create(name='DMZ', rabbitmq_queue_id='dmz')
    worker = approved_collector(groups=[group])
    admin = APIClient()
    admin.force_authenticate(User.objects.create_user('admin', password='x', is_staff=True))
    published.clear()

    resp = admin.patch(f'/api/collection-groups/{group.id}/', {'rabbitmq_queue_id': 'dmz2'}, format='json')

    assert resp.status_code == 200
    assert assignments(published, worker)[-1]['queues'] == ['collector.group.dmz2']


def test_driver_catalogue_only_counts_approved_collectors(db, worker_keys, approved_collector):
    workers.handle_event(worker_keys('pending').event(drivers=['mikrotik_ssh_export']))
    approved_collector('c1', drivers=['noop'])
    approved_collector('c2', drivers=['noop', 'binary_dummy'])

    catalogue = workers.driver_catalogue()

    assert list(catalogue) == ['binary_dummy', 'noop']
    assert catalogue['noop']['workers'] == 2
    assert catalogue['binary_dummy']['is_binary'] is True


# --- API --------------------------------------------------------------------------


@pytest.fixture
def admin():
    client = APIClient()
    client.force_authenticate(User.objects.create_user('admin', password='x', is_staff=True))
    return client


def test_admin_approves_a_worker_through_the_api(db, admin, worker_keys, published):
    group = CollectionGroup.objects.create(name='DMZ', rabbitmq_queue_id='dmz')
    worker = workers.handle_event(worker_keys().event())

    resp = admin.post(
        f'/api/workers/{worker.id}/approve/', {'role': 'collector', 'collection_groups': [group.id]}, format='json'
    )

    assert resp.status_code == 200, resp.content
    body = resp.json()
    assert (body['status'], body['assigned_queues'], body['in_sync']) == (
        STATUS_APPROVED,
        ['collector.group.dmz'],
        False,
    )
    assert body['approved_by_username'] == 'admin'
    assert len(published) == 1


@pytest.mark.parametrize(
    ('role', 'drivers', 'storage', 'target_driver', 'field'),
    [
        ('collector', (), (), None, 'role'),
        ('storage', ('noop',), (), None, 'role'),
        ('storage', ('noop',), ('filesystem',), 's3', 'storage_targets'),
    ],
)
def test_approval_must_match_what_the_worker_offers(
    db, admin, worker_keys, role, drivers, storage, target_driver, field
):
    from storage.models import StorageTarget

    worker = workers.handle_event(worker_keys().event(drivers=drivers, storage=storage))
    extra = {}
    if target_driver:
        extra['storage_targets'] = [str(StorageTarget.objects.create(name='t', driver=target_driver).pk)]

    resp = admin.post(f'/api/workers/{worker.id}/approve/', {'role': role, **extra}, format='json')

    assert resp.status_code == 400
    assert field in resp.json()
    assert Worker.objects.get(pk=worker.id).status == STATUS_PENDING


def test_forgetting_an_approved_worker_revokes_it_first(db, admin, approved_collector, published):
    worker = approved_collector()

    assert admin.delete(f'/api/workers/{worker.id}/').status_code == 204
    assert assignments(published, worker)[-1]['status'] == STATUS_REVOKED
    assert not Worker.objects.exists()


def test_orchestrator_fingerprint_is_published_to_admins(db, admin):
    resp = admin.get('/api/workers/orchestrator/')

    assert resp.json()['fingerprint'] == signing.fingerprint(public_key())


def test_backup_methods_come_from_approved_collectors(db, admin, approved_collector):
    assert admin.get('/api/backup-methods/').json() == []
    approved_collector()

    keys = [m['key'] for m in admin.get('/api/backup-methods/').json()]

    assert keys == ['binary_dummy', 'noop']
