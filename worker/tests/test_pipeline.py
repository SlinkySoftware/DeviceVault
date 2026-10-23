import hashlib
import uuid

import pytest

from devicevault_protocol import signing
from devicevault_protocol.jobs import (
    EVENT_COLLECTED,
    EVENT_FAILED,
    EVENT_RETRYING,
    EVENT_STARTED,
    EVENT_STORED,
    JOB_EVENT_TASK,
    blob_key,
)
from devicevault_protocol.names import STORE_TASK
from devicevault_protocol.tasks import sign_task
from devicevault_worker import identity as identity_store
from devicevault_worker.drivers.base import TransientError

ORCHESTRATOR = signing.generate_signing_key()


class FakeRedis:
    def __init__(self):
        self.data = {}

    def set(self, key, value, ex=None, nx=False):
        if nx and key in self.data:
            return None
        self.data[key] = value.encode() if isinstance(value, str) else value
        return True

    def expire(self, key, seconds):
        return key in self.data

    def eval(self, script, numkeys, key, value):
        # Only the device lock's compare-and-delete is used.
        if self.data.get(key) == value.encode():
            del self.data[key]

    def get(self, key):
        return self.data.get(key)

    def delete(self, key):
        self.data.pop(key, None)


class Sent:
    def __init__(self):
        self.tasks = []

    def __call__(self, name, args=None, queue=None, **kwargs):
        self.tasks.append((name, args, queue))

    def events(self):
        """Verified job events, as (event, payload)."""
        from devicevault_worker.app import identity

        public = signing.public_key_from_b64(identity.signing_public_key)
        return [
            (payload['event'], payload)
            for payload in (signing.verify(args[0], public) for name, args, _ in self.tasks if name == JOB_EVENT_TASK)
        ]

    def stores(self):
        return [(args, queue) for name, args, queue in self.tasks if name == STORE_TASK]


@pytest.fixture
def pipeline(monkeypatch, tmp_path):
    """Worker modules wired to a fake Redis and broker, trusting ORCHESTRATOR."""
    from devicevault_worker import app as app_module
    from devicevault_worker import blobs, collect

    monkeypatch.setenv('DV_STATE_DIR', str(tmp_path))
    identity_store.load_or_create().pin_orchestrator(signing.public_key_to_b64(ORCHESTRATOR))
    redis = FakeRedis()
    sent = Sent()
    monkeypatch.setattr(blobs, 'redis_client', redis)
    monkeypatch.setattr(collect, 'redis_client', redis)
    monkeypatch.setattr(app_module.app, 'send_task', sent)
    return redis, sent


def collect_job(tmp_path, *, driver='demo_config', params=None, storage='filesystem', vault=None):
    job_id = str(uuid.uuid4())
    store = {
        'job_id': job_id,
        'target': {'id': 't1', 'driver': storage},
        'config': {'path': 'store'},
        'name': {'device_key': '7-edge', 'job_id': job_id, 'timestamp': '20261023T000000Z', 'extension': '.cfg'},
    }
    job = {
        'job_id': job_id,
        'device': {'id': 7, 'name': 'edge', 'address': '192.0.2.1'},
        'driver': driver,
        'driver_params': params or {},
        'credentials': {},
        'timeout': 5,
        'encryption': {'kid': vault.current_kid, 'public_key': vault.public_key_b64()} if vault else None,
        'store': {'queue': 'storage.target.t1', 'envelope': sign_task(store, ORCHESTRATOR)},
    }
    return job_id, sign_task(job, ORCHESTRATOR)


def test_collected_backup_is_staged_and_handed_to_storage(pipeline, tmp_path):
    from devicevault_worker.collect import collect

    redis, sent = pipeline
    job_id, envelope = collect_job(tmp_path, params={'hostname': 'edge-01'})

    collect.run(envelope)

    events = sent.events()
    assert [event for event, _ in events] == [EVENT_STARTED, EVENT_COLLECTED]
    collected = events[1][1]
    staged = redis.get(blob_key(job_id))
    assert b'edge-01' in staged
    assert collected['sha256'] == hashlib.sha256(staged).hexdigest()
    assert collected['is_binary'] is False and collected['encrypted'] is False
    (args, queue), *_ = sent.stores()
    assert queue == 'storage.target.t1'
    assert args[1] == {'key': blob_key(job_id), 'sha256': collected['sha256'], 'size': len(staged)}


@pytest.mark.parametrize('signer', [None, signing.generate_signing_key()])
def test_unverifiable_collect_tasks_are_dropped(pipeline, tmp_path, signer):
    from devicevault_worker.collect import collect

    _, sent = pipeline
    _, envelope = collect_job(tmp_path)
    if signer is None:
        envelope = envelope['payload']
    else:
        envelope = sign_task(envelope['payload'], signer)

    collect.run(envelope)

    assert sent.tasks == []


def test_unknown_drivers_and_bad_params_fail_permanently(pipeline, tmp_path):
    from devicevault_worker.collect import collect

    _, sent = pipeline
    collect.run(collect_job(tmp_path, driver='no_such_driver')[1])
    collect.run(collect_job(tmp_path, params={'unexpected': True})[1])

    failures = [payload['error'] for event, payload in sent.events() if event == EVENT_FAILED]
    assert len(failures) == 2
    assert 'no "no_such_driver" driver' in failures[0]
    assert 'invalid driver parameters' in failures[1]
    assert sent.stores() == []


def test_transient_errors_are_reported_and_retried(pipeline, tmp_path, monkeypatch):
    from devicevault_worker import collect as collect_module

    _, sent = pipeline

    def unreachable(job, log):
        raise TransientError('connection refused')

    monkeypatch.setattr(collect_module, '_collect', unreachable)

    # Called directly, Celery's retry() re-raises the original exception.
    with pytest.raises(TransientError):
        collect_module.collect.run(collect_job(tmp_path)[1])

    assert [event for event, _ in sent.events()] == [EVENT_STARTED, EVENT_RETRYING]


def test_a_device_is_collected_by_one_job_at_a_time(pipeline, tmp_path):
    from devicevault_protocol.names import device_lock_key
    from devicevault_worker.collect import DeviceBusy, collect

    redis, sent = pipeline
    redis.set(device_lock_key(7), 'another-job')

    with pytest.raises(DeviceBusy):
        collect.run(collect_job(tmp_path)[1])

    assert [event for event, _ in sent.events()] == [EVENT_RETRYING]
    assert redis.get(device_lock_key(7)) == b'another-job'  # not ours to release


def test_a_redelivered_job_reclaims_its_own_lock(pipeline, tmp_path):
    from devicevault_protocol.names import device_lock_key
    from devicevault_worker.collect import collect

    redis, sent = pipeline
    job_id, envelope = collect_job(tmp_path)
    redis.set(device_lock_key(7), job_id)  # left behind by a worker that died mid-collection

    collect.run(envelope)

    assert [event for event, _ in sent.events()] == [EVENT_STARTED, EVENT_COLLECTED]
    assert redis.get(device_lock_key(7)) is None


def read_back(storage, ref):
    from devicevault_worker.storage.drivers import get_driver

    driver = get_driver(storage)
    return driver().read(ref, driver.Params(path='store'))


def volume_path():
    from devicevault_worker.storage.drivers import local

    return local.VOLUME


def run_store(sent):
    from devicevault_worker.storage.tasks import store

    (args, _), *_ = sent.stores()
    sent.tasks.clear()
    store.run(*args)
    return sent.events()


@pytest.mark.parametrize('storage', ['filesystem', 'git'])
def test_stored_backups_read_back_byte_for_byte(pipeline, tmp_path, storage):
    from devicevault_worker.collect import collect

    redis, sent = pipeline
    job_id, envelope = collect_job(tmp_path, storage=storage)
    collect.run(envelope)
    staged = redis.get(blob_key(job_id))

    events = run_store(sent)

    assert [event for event, _ in events] == [EVENT_STARTED, EVENT_STORED]
    stored = events[1][1]
    assert stored['sha256'] == hashlib.sha256(staged).hexdigest()
    assert redis.get(blob_key(job_id)) is None
    assert read_back(storage, stored['storage_ref']) == staged


def test_tampered_staged_backups_are_not_stored(pipeline, tmp_path):
    from devicevault_worker.collect import collect

    redis, sent = pipeline
    job_id, envelope = collect_job(tmp_path)
    collect.run(envelope)
    redis.set(blob_key(job_id), b'something else')

    events = run_store(sent)

    assert events[-1][0] == EVENT_FAILED
    assert 'does not match' in events[-1][1]['error']
    assert not list((volume_path() / 'store').rglob('*.cfg'))


def test_expired_staged_backups_fail(pipeline, tmp_path):
    from devicevault_worker.collect import collect

    redis, sent = pipeline
    job_id, envelope = collect_job(tmp_path)
    collect.run(envelope)
    redis.delete(blob_key(job_id))

    events = run_store(sent)

    assert events[-1][0] == EVENT_FAILED
    assert 'expired' in events[-1][1]['error']


# --- payload encryption --------------------------------------------------------------


def test_backups_are_encrypted_to_the_vault_before_staging(pipeline, tmp_path):
    from devicevault_protocol.crypto import VaultKeyRing, decrypt_backup, is_encrypted
    from devicevault_protocol.crypto.ecies import generate_private_key
    from devicevault_worker.collect import collect

    redis, sent = pipeline
    vault = VaultKeyRing({'v1': generate_private_key()})
    job_id, envelope = collect_job(tmp_path, params={'hostname': 'edge-01'}, vault=vault)

    collect.run(envelope)
    staged = redis.get(blob_key(job_id))
    stored = run_store(sent)[-1][1]

    assert is_encrypted(staged) and b'edge-01' not in staged
    assert b'edge-01' in decrypt_backup(staged, vault)
    assert read_back('filesystem', stored['storage_ref']) == staged


def test_secrets_sealed_for_this_worker_are_opened(pipeline):
    from devicevault_protocol.crypto import seal
    from devicevault_protocol.crypto.ecies import generate_private_key
    from devicevault_worker.app import identity
    from devicevault_worker.drivers.base import PermanentError
    from devicevault_worker.payload import secret

    mine = seal({'password': 'p'}, identity.encryption_key.public_key())
    theirs = seal({'password': 'p'}, generate_private_key().public_key())

    assert secret({'credentials': {'password': 'plain'}}, 'credentials') == {'password': 'plain'}
    assert secret({'credentials_sealed': {identity.worker_id: mine}}, 'credentials') == {'password': 'p'}
    with pytest.raises(PermanentError, match='not sealed for this worker'):
        secret({'credentials_sealed': {'someone-else': theirs}}, 'credentials')
    with pytest.raises(PermanentError, match='could not open'):
        secret({'credentials_sealed': {identity.worker_id: theirs}}, 'credentials')


def test_check_reports_whether_a_target_works(pipeline):
    from devicevault_worker.storage.tasks import check

    ok = check.run(sign_task({'target': {'id': 't1', 'driver': 'filesystem'}, 'config': {'path': 'ok'}}, ORCHESTRATOR))
    bad = check.run(
        sign_task({'target': {'id': 't1', 'driver': 'filesystem'}, 'config': {'path': '../x'}}, ORCHESTRATOR)
    )
    unknown = check.run(sign_task({'target': {'id': 't1', 'driver': 'tape'}, 'config': {}}, ORCHESTRATOR))
    forged = check.run(sign_task({'target': {'id': 't1', 'driver': 'filesystem'}}, signing.generate_signing_key()))

    assert ok['status'] == 'success' and 'writable' in ok['message']
    assert bad['status'] == 'failure' and 'invalid storage target settings' in bad['error']
    assert 'no "tape" storage driver' in unknown['error']
    assert 'task rejected' in forged['error']
