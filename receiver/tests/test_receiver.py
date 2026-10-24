import subprocess
import sys

import pytest

from devicevault_protocol import blobs
from devicevault_protocol.crypto import EncryptionHeader, VaultKeyRing, decrypt_backup, seal
from devicevault_protocol.crypto.ecies import generate_private_key
from devicevault_protocol.jobs import blob_key
from devicevault_protocol.push import PUSH_EVENT_TASK
from devicevault_protocol.registration import ORCHESTRATOR_QUEUE
from devicevault_receiver import events as events_module
from devicevault_receiver.config import ReceiverConfig
from devicevault_receiver.ingest import Ingestor, is_text

DEVICE = {'id': 7, 'ip': '192.0.2.10', 'push_mode': 'ssh', 'filename_pattern': '*-confg'}


def test_receiver_imports_without_django():
    # Fresh interpreter with Django made unimportable, as in the receiver image.
    code = (
        "import sys; sys.modules['django'] = None; "
        'import devicevault_receiver.main, devicevault_receiver.ssh, devicevault_receiver.agent'
    )
    result = subprocess.run([sys.executable, '-c', code], capture_output=True, text=True, check=False)

    assert result.returncode == 0, result.stderr


# --- configuration --------------------------------------------------------------------


def test_the_sealed_password_is_opened_and_devices_are_found_by_any_spelling():
    from devicevault_receiver.app import identity

    sealed = seal('pw', identity.encryption_key.public_key())
    config = ReceiverConfig.from_assignment(
        {'ssh': {'enabled': True, 'password_sealed': {identity.worker_id: sealed}}, 'devices': [DEVICE], 'new': 1},
        identity,
    )

    assert config.ssh.password == 'pw' and config.ssh.port == 2222
    assert config.device_for('::ffff:192.0.2.10').id == 7
    assert config.device_for('192.0.2.11') is None and config.device_for('not an address') is None


def test_a_password_sealed_for_others_leaves_none():
    from devicevault_receiver.app import identity

    config = ReceiverConfig.from_assignment({'ssh': {'password_sealed': {'someone-else': 'x'}}}, identity)

    assert config.ssh.password == ''


def test_the_default_configuration_listens_for_nothing():
    config = ReceiverConfig()

    assert not config.ssh.enabled and config.devices == () and config.encryption is None


# --- ingesting --------------------------------------------------------------------------


@pytest.mark.parametrize(
    ('content', 'text'),
    [(b'hostname edge\n', True), ('café\n'.encode(), True), (b'\x00\x01', False), (b'\xff\xfe', False), (b'', True)],
)
def test_text_is_told_from_binary(tmp_path, content, text):
    path = tmp_path / 'f'
    path.write_bytes(content)
    with open(path, 'rb') as handle:
        assert is_text(handle) is text


def ingest(redis, events, spool, tmp_path, config, content=b'hostname edge\n'):
    upload = tmp_path / 'upload'
    upload.write_bytes(content)
    device = config.device_for('192.0.2.10')
    job_id = Ingestor(redis=redis, events=events, spool_dir=spool).ingest(
        config=config, device=device, source_ip='192.0.2.10', protocol='ssh', filename='edge-confg', path=upload
    )
    return job_id


def test_an_upload_is_staged_and_reported(redis, events, sent, spool, tmp_path):
    config = ReceiverConfig(devices=[DEVICE])

    job_id = ingest(redis, events, spool, tmp_path, config)

    assert blobs.get(redis, blob_key(job_id)) == b'hostname edge\n'
    [(name, _, queue, kwargs)] = sent.tasks
    assert (name, queue, kwargs['expires']) == (PUSH_EVENT_TASK, ORCHESTRATOR_QUEUE, 24 * 3600)
    [event] = sent.events()
    assert event['event'] == 'received' and event['job_id'] == job_id
    assert (event['device_id'], event['source_ip'], event['protocol'], event['filename']) == (
        7,
        '192.0.2.10',
        'ssh',
        'edge-confg',
    )
    assert event['blob'] == {'key': blob_key(job_id), 'sha256': blobs.sha256(b'hostname edge\n'), 'size': 14}
    assert (event['is_binary'], event['encrypted']) == (False, False)
    assert 'edge-confg' in event['log'][0]['message']


def test_with_payload_encryption_uploads_are_encrypted_to_the_vault(redis, events, sent, spool, tmp_path):
    vault = VaultKeyRing({'v1': generate_private_key()})
    config = ReceiverConfig(
        devices=[DEVICE], encryption={'kid': vault.current_kid, 'public_key': vault.public_key_b64()}
    )

    job_id = ingest(redis, events, spool, tmp_path, config, content=b'\x00binary')

    staged = blobs.get(redis, blob_key(job_id))
    assert b'binary' not in staged
    assert decrypt_backup(staged, vault) == b'\x00binary'
    assert (
        EncryptionHeader.from_bytes(staged).aad | {'job_id': job_id, 'device_id': 7}
        == EncryptionHeader.from_bytes(staged).aad
    )
    [event] = sent.events()
    assert (event['is_binary'], event['encrypted']) == (True, True)
    assert list(spool.iterdir()) == []  # the encrypted copy is gone


# --- rejections ---------------------------------------------------------------------------


def test_rejections_are_reported_once_per_window(events, sent, monkeypatch):
    clock = [1000.0]
    monkeypatch.setattr(events_module.time, 'monotonic', lambda: clock[0])

    for _ in range(3):
        events.rejected(source_ip='198.51.100.1', protocol='ssh', reason='auth_failed')
    events.rejected(source_ip='198.51.100.1', protocol='ssh', reason='filename', filename='x')
    events.rejected(source_ip='198.51.100.2', protocol='ssh', reason='auth_failed')
    clock[0] += 61
    events.rejected(source_ip='198.51.100.1', protocol='ssh', reason='auth_failed')

    reported = [(e['source_ip'], e['reason']) for e in sent.events()]
    assert reported == [
        ('198.51.100.1', 'auth_failed'),
        ('198.51.100.1', 'filename'),
        ('198.51.100.2', 'auth_failed'),
        ('198.51.100.1', 'auth_failed'),
    ]


def test_a_broker_outage_does_not_break_rejections(events, monkeypatch):
    def down(*args, **kwargs):
        raise ConnectionError('broker down')

    monkeypatch.setattr(events, '_send_task', down)

    events.rejected(source_ip='198.51.100.1', protocol='ssh', reason='auth_failed')  # logged, not raised
