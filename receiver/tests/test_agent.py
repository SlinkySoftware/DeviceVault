import asyncio
import threading

import asyncssh
import pytest

from devicevault_protocol import identity as identity_store
from devicevault_protocol import signing
from devicevault_protocol.crypto import seal
from devicevault_protocol.registration import ASSIGNMENT, STATUS_APPROVED, STATUS_REVOKED
from devicevault_protocol.tasks import ORCHESTRATOR_SIGNER
from devicevault_receiver.agent import ReceiverAgent
from devicevault_receiver.ingest import Ingestor
from devicevault_receiver.receiver import Receiver

ORCHESTRATOR = signing.generate_signing_key()


@pytest.fixture
def agent(tmp_path, redis, events, spool):
    loop = asyncio.new_event_loop()
    thread = threading.Thread(target=loop.run_forever, daemon=True)
    thread.start()
    identity = identity_store.load_or_create(tmp_path / 'identity.json')
    receiver = Receiver(
        ingestor=Ingestor(redis=redis, events=events, spool_dir=spool),
        events=events,
        host_key=asyncssh.generate_private_key('ssh-ed25519'),
        spool_dir=spool,
    )
    sent = []
    agent = ReceiverAgent(
        receiver=receiver,
        loop=loop,
        identity=identity,
        name='receiver-1',
        broker_url='memory://',
        send_task=lambda name, **kwargs: sent.append((name, kwargs)),
    )
    agent.sent = sent
    yield agent
    asyncio.run_coroutine_threadsafe(receiver.close(), loop).result()
    loop.call_soon_threadsafe(loop.stop)
    thread.join()


def assignment(identity, version, status=STATUS_APPROVED, receiver=None):
    payload = {
        'type': ASSIGNMENT,
        'worker_id': identity.worker_id,
        'version': version,
        'status': status,
        'role': 'receiver',
        'queues': [],
        'orchestrator_key': signing.public_key_to_b64(ORCHESTRATOR),
        'receiver': receiver or {},
    }
    return signing.sign(payload, ORCHESTRATOR, ORCHESTRATOR_SIGNER)


def test_assignments_configure_the_receiver(agent):
    identity = agent.identity
    section = {
        'ssh': {
            'enabled': False,
            'username': 'dv',
            'password_sealed': {identity.worker_id: seal('pw', identity.encryption_key.public_key())},
        },
        'devices': [{'id': 7, 'ip': '192.0.2.10', 'push_mode': 'ssh'}],
        'encryption': {'kid': 'v1', 'public_key': 'x'},
    }

    assert agent.handle_assignment(assignment(identity, 1, receiver=section))

    config = agent.receiver.config
    assert config.ssh.password == 'pw' and config.device_for('192.0.2.10').id == 7
    report = agent.report()['receiver']
    assert (report['vault_kid'], report['devices']) == ('v1', 1)
    assert report['host_key_fingerprint'].startswith('SHA256:')
    assert report['monitoring'] | {'certificate_fingerprint': None} == {
        'enabled': False,
        'port': 8443,
        'listening': False,
        'error': '',
        'certificate_fingerprint': None,
        'tokens': 0,
        'snapshots': {},
        'requests': 0,
        'refused': 0,
        'throttled': 0,
    }
    assert agent.event_payload()['capabilities']['receiver']['protocols'] == ['ssh', 'tftp']

    agent.handle_assignment(assignment(identity, 2, status=STATUS_REVOKED, receiver=section))
    assert agent.receiver.config.devices == ()


def test_an_unusable_section_listens_for_nothing(agent):
    agent.handle_assignment(assignment(agent.identity, 1, receiver={'ssh': {'port': 'not a port'}, 'devices': [1]}))

    assert agent.applied_version == 1
    assert agent.receiver.config.devices == () and not agent.receiver.config.ssh.enabled
