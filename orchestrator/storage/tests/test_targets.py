import pytest

from core import workers
from core.signing import public_key
from devicevault_protocol import signing
from storage import service
from storage.models import StorageTarget

ORCHESTRATOR = lambda: signing.public_key_from_b64(public_key())  # noqa: E731


@pytest.fixture
def admin(admin_client):
    return admin_client


@pytest.fixture
def storage_worker(db, worker_keys):
    def make(name='storage-1', drivers=('filesystem', 'git', 's3')):
        return workers.approve(workers.handle_event(worker_keys(name).event(storage=drivers)), role='storage')

    return make


def last_queues(published, worker):
    envelopes = [env for wid, env in published if wid == str(worker.id)]
    return signing.verify(envelopes[-1], ORCHESTRATOR())['queues']


def test_assigning_a_target_pushes_its_queue(admin, storage_worker, published):
    worker = storage_worker()

    reply = admin.post(
        '/api/storage-targets/',
        {'name': 'Local', 'driver': 'filesystem', 'config': {'path': 'fs'}, 'workers': [str(worker.id)]},
        format='json',
    )

    assert reply.status_code == 201, reply.content
    target = StorageTarget.objects.get()
    assert reply.json()['queue'] == f'storage.target.{target.id}'
    assert last_queues(published, worker) == [target.queue]
    assert worker.assigned_queues() == [target.queue]

    admin.patch(f'/api/storage-targets/{target.id}/', {'workers': []}, format='json')
    assert last_queues(published, worker) == []


def test_settings_are_validated_against_the_driver_schema(admin, storage_worker):
    storage_worker()

    unknown = admin.post('/api/storage-targets/', {'name': 'x', 'driver': 'tape', 'config': {}}, format='json')
    invalid = admin.post(
        '/api/storage-targets/', {'name': 'x', 'driver': 'filesystem', 'config': {'compress': 1}}, format='json'
    )

    assert 'driver' in unknown.json()
    assert invalid.status_code == 400
    assert any("'path' is a required property" in e for e in invalid.json()['config'])


def test_only_shareable_drivers_get_several_workers(admin, storage_worker):
    a, b = storage_worker('storage-a'), storage_worker('storage-b')
    both = [str(a.id), str(b.id)]

    local = admin.post(
        '/api/storage-targets/',
        {'name': 'l', 'driver': 'filesystem', 'config': {'path': 'fs'}, 'workers': both},
        format='json',
    )
    bucket = admin.post(
        '/api/storage-targets/',
        {'name': 'b', 'driver': 's3', 'config': {'bucket': 'bk'}, 'workers': both},
        format='json',
    )

    assert local.status_code == 400 and 'only one worker' in local.json()['workers'][0]
    assert bucket.status_code == 201


def test_workers_must_offer_the_driver(admin, storage_worker):
    storage_worker('storage-s3', drivers=('s3',))
    worker = storage_worker(drivers=('filesystem',))

    reply = admin.post(
        '/api/storage-targets/',
        {'name': 'b', 'driver': 's3', 'config': {'bucket': 'bk'}, 'workers': [str(worker.id)]},
        format='json',
    )

    assert 'does not offer the "s3"' in reply.json()['workers'][0]


def test_secrets_are_write_only_and_kept_when_left_blank(admin, storage_worker):
    storage_worker()
    created = admin.post(
        '/api/storage-targets/',
        {'name': 'b', 'driver': 's3', 'config': {'bucket': 'bk', 'secret_access_key': 'sk'}},
        format='json',
    ).json()

    assert created['config'] == {'bucket': 'bk', 'secret_access_key': None}
    assert created['secrets_set'] == ['secret_access_key']

    admin.patch(
        f'/api/storage-targets/{created["id"]}/',
        {'config': {'bucket': 'other', 'secret_access_key': None}},
        format='json',
    )
    assert StorageTarget.objects.get().config == {'bucket': 'other', 'secret_access_key': 'sk'}


def test_targets_holding_backups_cannot_be_deleted_or_change_driver(admin, setup):
    from backups.models import BackupJob

    target = setup['target']
    BackupJob.objects.create(device=setup['device'], storage_target=target, driver='noop')

    deleted = admin.delete(f'/api/storage-targets/{target.id}/')
    changed = admin.patch(f'/api/storage-targets/{target.id}/', {'driver': 'git'}, format='json')

    assert deleted.status_code == 409
    assert changed.status_code == 400 and 'driver' in changed.json()


def test_deleting_a_target_takes_its_queue_away(admin, setup, published):
    storage = workers.Worker.objects.get(pk=setup['storage'].id)
    setup['device'].delete()

    assert admin.delete(f'/api/storage-targets/{setup["target"].id}/').status_code == 204
    assert last_queues(published, storage) == []


def test_check_reports_what_the_worker_said(admin, setup, monkeypatch):
    sent = []

    def ask(target, task, spec, timeout):
        sent.append((task, spec))
        return {'status': 'success', 'message': '/srv/devicevault/fs is writable', 'worker_id': setup['storage'].id}

    monkeypatch.setattr(service, 'ask', ask)

    reply = admin.post(f'/api/storage-targets/{setup["target"].id}/check/').json()

    assert reply == {'ok': True, 'message': '/srv/devicevault/fs is writable', 'worker': 'storage-1'}
    [(task, spec)] = sent
    assert task == 'storage.check' and spec['config'] == {'path': 'fs'}


def test_check_without_workers_explains(admin, setup):
    setup['target'].workers.clear()

    reply = admin.post(f'/api/storage-targets/{setup["target"].id}/check/').json()

    assert reply['ok'] is False and 'no approved storage worker' in reply['error']


def test_storage_drivers_come_from_approved_workers(admin, storage_worker):
    storage_worker(drivers=('s3',))

    [driver] = admin.get('/api/storage-drivers/').json()

    assert (driver['key'], driver['shareable'], driver['workers']) == ('s3', True, 1)


def test_approving_a_storage_worker_with_targets(admin, worker_keys, published):
    target = StorageTarget.objects.create(name='Local', driver='filesystem', config={'path': 'fs'})
    worker = workers.handle_event(worker_keys('storage-1').event())

    reply = admin.post(
        f'/api/workers/{worker.id}/approve/', {'role': 'storage', 'storage_targets': [str(target.id)]}, format='json'
    )

    assert reply.status_code == 200, reply.content
    assert last_queues(published, worker) == [target.queue]

    other = workers.handle_event(worker_keys('storage-2').event())
    clash = admin.post(
        f'/api/workers/{other.id}/approve/', {'role': 'storage', 'storage_targets': [str(target.id)]}, format='json'
    )
    assert clash.status_code == 400 and 'only one worker' in clash.json()['storage_targets'][0]


def test_an_approved_storage_worker_can_be_given_targets(admin, storage_worker, published):
    worker = storage_worker()
    target = StorageTarget.objects.create(name='Local', driver='filesystem', config={'path': 'fs'})

    reply = admin.patch(f'/api/workers/{worker.id}/', {'storage_targets': [str(target.id)]}, format='json')
    assert reply.status_code == 200, reply.content
    assert last_queues(published, worker) == [target.queue]

    admin.patch(f'/api/workers/{worker.id}/', {'role': 'collector'}, format='json')
    assert not target.workers.exists()
