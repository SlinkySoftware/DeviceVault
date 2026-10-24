import uuid

import pytest

from audit.models import AuditLog
from backups.models import BackupJob
from core import keys
from core.models import Worker
from devicevault_protocol import signing
from devicevault_protocol.crypto import unseal
from devicevault_protocol.jobs import blob_key
from devicevault_protocol.push import EVENT_RECEIVED, EVENT_REJECTED
from devicevault_protocol.tasks import verify_task
from push.events import EventRejected, handle_push_event
from push.models import PushRejection
from push.service import settings_for
from push.tests.conftest import RECEIVER_CAPABILITIES, push_event

SHA = 'b' * 64


def last_assignment(published, worker):
    envelope = [e for worker_id, e in published if worker_id == str(worker.pk)][-1]
    return signing.peek(envelope)


def enable_push(device, **fields):
    for field, value in {'push_mode': 'ssh', **fields}.items():
        setattr(device, field, value)
    device.save()


# --- assignments ----------------------------------------------------------------------


def test_a_receiver_is_told_its_settings_and_the_devices_that_push(
    setup, receiver, published, django_capture_on_commit_callbacks
):
    _, worker = receiver
    settings = settings_for(worker)
    settings.ssh_enabled = True
    settings.ssh_secret = {'password': 'pw'}
    settings.save()
    with django_capture_on_commit_callbacks(execute=True):
        enable_push(setup['device'], push_filename_pattern='*-confg')

    section = last_assignment(published, worker)['receiver']

    assert section['ssh'] | {'password': None} == {
        'enabled': True,
        'port': 2222,
        'username': 'devicevault',
        'password': None,
        'authorized_keys': '',
    }
    assert section['ssh']['password'] == 'pw'  # payload encryption is off in tests
    assert section['devices'] == [
        {'id': setup['device'].pk, 'ip': '192.0.2.10', 'push_mode': 'ssh', 'filename_pattern': '*-confg'}
    ]
    assert section['max_file_size'] == 512 * 1024 * 1024 and section['encryption'] is None
    assert section['tftp'] == {'enabled': False, 'port': 6969}


def test_with_payload_encryption_the_password_is_sealed_to_the_receiver(settings, receiver, published, worker_keys):
    settings.DEVICEVAULT_PAYLOAD_ENCRYPTION = True
    keys_, worker = receiver
    receiver_settings = settings_for(worker)
    receiver_settings.ssh_secret = {'password': 'pw'}
    receiver_settings.save()
    from core.workers import update_assignment

    update_assignment(worker)
    section = last_assignment(published, worker)['receiver']

    assert 'password' not in section['ssh']
    assert unseal(section['ssh']['password_sealed'][str(worker.pk)], keys_.encryption) == 'pw'
    assert section['encryption'] == keys.vault_public()


def test_receivers_hear_about_push_changes_only(setup, receiver, django_capture_on_commit_callbacks):
    _, worker = receiver
    device = setup['device']

    def version_after(change):
        with django_capture_on_commit_callbacks(execute=True):
            change()
        return Worker.objects.get(pk=worker.pk).desired_version

    start = Worker.objects.get(pk=worker.pk).desired_version
    assert version_after(lambda: enable_push(device)) == start + 1
    assert version_after(lambda: enable_push(device, name='renamed')) == start + 1  # nothing receivers know
    assert version_after(lambda: enable_push(device, ip_address='192.0.2.99')) == start + 2
    assert version_after(lambda: enable_push(device, push_mode='off')) == start + 3
    assert version_after(lambda: enable_push(device, push_mode='off', ip_address='192.0.2.98')) == start + 3
    enable_push(device)
    assert version_after(device.delete) > start + 3


def test_a_receiver_reporting_an_old_vault_key_is_updated(settings, receiver, worker_keys):
    from core import workers

    settings.DEVICEVAULT_PAYLOAD_ENCRYPTION = True
    keys_, worker = receiver
    stale = {'receiver': {'vault_kid': 'old', 'listeners': {}}}
    current = {'receiver': {'vault_kid': keys.vault_public()['kid'], 'listeners': {}}}
    version = worker.desired_version

    worker = workers.handle_event(keys_.event(applied_version=version, capabilities=RECEIVER_CAPABILITIES, **current))
    assert worker.desired_version == version
    worker = workers.handle_event(keys_.event(applied_version=version, capabilities=RECEIVER_CAPABILITIES, **stale))
    assert worker.desired_version == version + 1
    assert worker.runtime == stale


# --- received ---------------------------------------------------------------------------


def received(keys_, device, job_id=None, **overrides):
    job_id = job_id or str(uuid.uuid4())
    details = {
        'job_id': job_id,
        'device_id': device.pk,
        'source_ip': '::ffff:192.0.2.10',
        'filename': 'edge-confg',
        'blob': {'key': blob_key(job_id), 'sha256': SHA, 'size': 12},
        'is_binary': False,
        'encrypted': True,
        'duration_ms': 3,
        'log': [{'source': 'receiver', 'severity': 'INFO', 'message': 'received', 'timestamp': 'now'}],
        **overrides,
    }
    return job_id, push_event(keys_, EVENT_RECEIVED, **details)


def test_a_pushed_file_becomes_a_collected_job_sent_to_storage(
    setup, receiver, broker, django_capture_on_commit_callbacks
):
    keys_, _ = receiver
    enable_push(setup['device'])
    job_id, envelope = received(keys_, setup['device'])

    with django_capture_on_commit_callbacks(execute=True):
        job = handle_push_event(envelope)

    assert str(job.pk) == job_id
    assert (job.state, job.trigger, job.driver, job.source_filename) == ('collected', 'push', 'push:ssh', 'edge-confg')
    assert (job.collected_sha256, job.size_bytes, job.encrypted, job.collector) == (SHA, 12, True, 'receiver-1')
    [(name, [store, blob], queue)] = broker.sent
    assert (name, queue) == ('job.store', setup['target'].queue)
    assert blob == {'key': blob_key(job_id), 'sha256': SHA, 'size': 12}
    from core.signing import public_key

    spec = verify_task(store, signing.public_key_from_b64(public_key()))
    assert spec['job_id'] == job_id and spec['name']['extension'] == '.cfg'


def test_push_jobs_ignore_the_one_active_job_rule_and_redelivery(
    setup, receiver, broker, django_capture_on_commit_callbacks
):
    keys_, _ = receiver
    enable_push(setup['device'])
    first_id, first = received(keys_, setup['device'])
    _, second = received(keys_, setup['device'])

    with django_capture_on_commit_callbacks(execute=True):
        handle_push_event(first)
        handle_push_event(second)
        assert handle_push_event(first) is None  # redelivered

    assert BackupJob.objects.filter(device=setup['device'], trigger='push').count() == 2
    assert len(broker.sent) == 2


@pytest.mark.parametrize(
    ('change', 'detail'),
    [
        ({'push_mode': 'off'}, 'does not push over ssh'),
        ({'ip_address': '192.0.2.77'}, 'address is now 192.0.2.77'),
        ({'push_filename_pattern': '*.cfg'}, 'does not match'),
        ({'enabled': False}, 'disabled'),
    ],
)
def test_pushes_for_devices_that_changed_meanwhile_are_discarded(setup, receiver, broker, change, detail):
    keys_, worker = receiver
    enable_push(setup['device'], **change)
    _, envelope = received(keys_, setup['device'])

    assert handle_push_event(envelope) is None

    assert not BackupJob.objects.filter(trigger='push').exists() and broker.sent == []
    rejection = PushRejection.objects.get(worker=worker)
    assert (rejection.reason, rejection.source_ip) == ('device_changed', '192.0.2.10')
    assert detail in rejection.detail


def test_a_blob_key_must_belong_to_the_job(setup, receiver, broker):
    keys_, _ = receiver
    enable_push(setup['device'])
    _, envelope = received(keys_, setup['device'], blob={'key': 'dv:blob:job:other', 'sha256': SHA, 'size': 1})

    assert handle_push_event(envelope) is None
    assert not BackupJob.objects.exists()


def test_only_approved_receivers_send_push_events(setup, receiver, worker_keys):
    from core import workers

    keys_, worker = receiver
    collector = worker_keys('collector-x')
    workers.approve(workers.handle_event(collector.event()), role='collector')
    _, from_collector = received(collector, setup['device'])
    _, forged = received(keys_, setup['device'])
    forged['payload']['filename'] = 'other'

    for envelope in (from_collector, forged):
        with pytest.raises(EventRejected):
            handle_push_event(envelope)
    workers.revoke(worker)
    with pytest.raises(EventRejected):
        handle_push_event(received(keys_, setup['device'])[1])


# --- rejected ---------------------------------------------------------------------------


def test_rejections_are_recorded_audited_and_pruned(receiver, monkeypatch):
    keys_, worker = receiver
    monkeypatch.setattr(PushRejection, 'KEEP', 3)

    for n in range(5):
        handle_push_event(
            push_event(keys_, EVENT_REJECTED, source_ip=f'198.51.100.{n}', reason='unknown_source', filename='x')
        )
    handle_push_event(push_event(keys_, EVENT_REJECTED, source_ip='198.51.100.9', reason='nonsense'))

    kept = list(PushRejection.objects.filter(worker=worker).values_list('source_ip', 'reason'))
    assert kept == [('198.51.100.9', 'error'), ('198.51.100.4', 'unknown_source'), ('198.51.100.3', 'unknown_source')]
    audit = AuditLog.objects.filter(action='push.rejected')
    assert audit.count() == 6
    assert audit.first().outcome == AuditLog.DENIED and audit.first().actor_name == 'receiver-1'


def test_tftp_pushes_need_a_tftp_device(setup, receiver, broker, django_capture_on_commit_callbacks):
    keys_, worker = receiver
    enable_push(setup['device'], push_mode='tftp')
    _, envelope = received(keys_, setup['device'])  # claims ssh
    assert handle_push_event(envelope) is None
    assert PushRejection.objects.get(worker=worker).detail == 'the device does not push over ssh'

    job_id = str(uuid.uuid4())
    details = {
        'job_id': job_id,
        'device_id': setup['device'].pk,
        'source_ip': '192.0.2.10',
        'filename': 'edge-confg',
        'blob': {'key': blob_key(job_id), 'sha256': SHA, 'size': 12},
    }
    with django_capture_on_commit_callbacks(execute=True):
        job = handle_push_event(push_event(keys_, EVENT_RECEIVED, **{**details, 'protocol': 'tftp'}))

    assert job.driver == 'push:tftp' and len(broker.sent) == 1
