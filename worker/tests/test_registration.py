import stat
import time
from datetime import UTC, datetime, timedelta

import pytest

from devicevault_protocol import signing
from devicevault_protocol.registration import (
    ASSIGNMENT,
    EVENT_HEARTBEAT,
    EVENT_REGISTER,
    ORCHESTRATOR_QUEUE,
    STATUS_APPROVED,
    STATUS_PENDING,
    STATUS_REVOKED,
    WORKER_EVENT_TASK,
)
from devicevault_protocol.tasks import ORCHESTRATOR_SIGNER
from devicevault_worker import identity as identity_store
from devicevault_worker.agent import RegistrationAgent

ORCHESTRATOR = signing.generate_signing_key()
ORCHESTRATOR_KEY = signing.public_key_to_b64(ORCHESTRATOR)


class FakeControl:
    def __init__(self):
        self.calls = []

    def add_consumer(self, queue, **kwargs):
        self.calls.append(('add', queue, kwargs['destination']))

    def cancel_consumer(self, queue, **kwargs):
        self.calls.append(('cancel', queue, kwargs['destination']))


@pytest.fixture
def identity(tmp_path):
    return identity_store.load_or_create(tmp_path / 'identity.json')


@pytest.fixture
def agent(identity):
    sent = []
    agent = RegistrationAgent(
        identity=identity,
        celery_hostname='collector-1@host',
        control=FakeControl(),
        send_task=lambda name, **kwargs: sent.append((name, kwargs)),
    )
    agent.sent = sent
    return agent


def assignment(
    identity, *, version=1, status=STATUS_APPROVED, queues=('collector.group.dmz',), key=ORCHESTRATOR, **extra
):
    now = extra.pop('now', None)
    payload = {
        'type': ASSIGNMENT,
        'worker_id': identity.worker_id,
        'version': version,
        'status': status,
        'role': 'collector',
        'queues': list(queues),
        'orchestrator_key': signing.public_key_to_b64(key),
        **extra,
    }
    return signing.sign(payload, key, ORCHESTRATOR_SIGNER, now=now)


# --- identity -------------------------------------------------------------------------


def test_identity_is_created_once_and_persisted_privately(tmp_path):
    path = tmp_path / 'identity.json'
    first = identity_store.load_or_create(path)
    again = identity_store.load_or_create(path)

    assert again.worker_id == first.worker_id
    assert again.fingerprint == first.fingerprint
    assert stat.S_IMODE(path.stat().st_mode) == 0o600


def test_pinned_key_is_visible_to_other_processes(monkeypatch, tmp_path):
    monkeypatch.setenv('DV_STATE_DIR', str(tmp_path))
    identity = identity_store.load_or_create()
    assert identity_store.pinned_orchestrator_key() is None

    time.sleep(0.01)  # distinct mtime
    identity.pin_orchestrator(ORCHESTRATOR_KEY)

    assert signing.public_key_to_b64(identity_store.pinned_orchestrator_key()) == ORCHESTRATOR_KEY


# --- events ---------------------------------------------------------------------------


def test_events_are_signed_by_the_worker_and_switch_to_heartbeats(agent, identity):
    agent.send_event()
    name, kwargs = agent.sent[-1]
    payload = signing.verify(kwargs['args'][0], identity.signing_key.public_key())

    assert (name, kwargs['queue']) == (WORKER_EVENT_TASK, ORCHESTRATOR_QUEUE)
    assert payload['event'] == EVENT_REGISTER
    assert payload['signing_key'] == identity.signing_public_key
    assert {d['key'] for d in payload['capabilities']['collector_drivers']} >= {'noop', 'binary_dummy'}

    agent.handle_assignment(assignment(identity))
    agent.send_event()
    heartbeat = signing.verify(agent.sent[-1][1]['args'][0], identity.signing_key.public_key())
    assert (heartbeat['event'], heartbeat['applied_version']) == (EVENT_HEARTBEAT, 1)


# --- assignments ----------------------------------------------------------------------


def test_first_approval_pins_the_orchestrator_and_adds_queues(agent, identity):
    assert agent.handle_assignment(assignment(identity, queues=['collector.group.a', 'collector.group.b']))

    assert identity.orchestrator_key == ORCHESTRATOR_KEY
    assert identity_store.load(identity.path).orchestrator_key == ORCHESTRATOR_KEY
    assert agent._control.calls == [
        ('add', 'collector.group.a', ['collector-1@host']),
        ('add', 'collector.group.b', ['collector-1@host']),
    ]


def test_later_assignments_apply_the_difference(agent, identity):
    agent.handle_assignment(assignment(identity, version=1, queues=['collector.group.a', 'collector.group.b']))
    agent._control.calls.clear()

    agent.handle_assignment(assignment(identity, version=2, queues=['collector.group.b', 'collector.group.c']))

    assert agent._control.calls == [
        ('add', 'collector.group.c', ['collector-1@host']),
        ('cancel', 'collector.group.a', ['collector-1@host']),
    ]
    assert agent.queues == {'collector.group.b', 'collector.group.c'}


def test_revocation_cancels_every_queue(agent, identity):
    agent.handle_assignment(assignment(identity, version=1))
    agent.handle_assignment(assignment(identity, version=2, status=STATUS_REVOKED, queues=[]))

    assert agent.queues == set()
    assert agent.status == STATUS_REVOKED


def test_a_different_orchestrator_key_is_rejected_after_pinning(agent, identity):
    agent.handle_assignment(assignment(identity))

    impostor = signing.generate_signing_key()
    assert not agent.handle_assignment(assignment(identity, version=5, key=impostor, queues=['collector.group.evil']))
    assert 'collector.group.evil' not in agent.queues
    assert identity.orchestrator_key == ORCHESTRATOR_KEY


def test_nothing_is_pinned_until_an_approval(agent, identity):
    assert not agent.handle_assignment(assignment(identity, status=STATUS_PENDING, queues=[]))
    assert identity.orchestrator_key is None


@pytest.mark.parametrize(
    'make',
    [
        # Forged: claims the orchestrator key but is signed by another key.
        lambda i: {**assignment(i, key=signing.generate_signing_key()), 'payload': assignment(i)['payload']},
        lambda i: assignment(i, worker_id='00000000-0000-0000-0000-000000000000'),
        lambda i: assignment(i, now=datetime.now(UTC) - timedelta(hours=1)),
        lambda i: signing.sign(assignment(i)['payload'], ORCHESTRATOR, 'not-the-orchestrator'),
        lambda i: {'type': 'assignment'},
    ],
    ids=['forged', 'other-worker', 'expired', 'wrong-signer', 'unsigned'],
)
def test_invalid_assignments_change_nothing(agent, identity, make):
    assert not agent.handle_assignment(make(identity))
    assert agent.queues == set()
    assert identity.orchestrator_key is None


def test_stale_versions_are_ignored(agent, identity):
    agent.handle_assignment(assignment(identity, version=3, queues=['collector.group.new']))

    assert not agent.handle_assignment(assignment(identity, version=2, queues=['collector.group.old']))
    assert agent.queues == {'collector.group.new'}
