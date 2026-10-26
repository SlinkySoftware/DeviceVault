"""The monitoring relay: token checks, rate limit, snapshot loading, TLS, and requests over HTTPS."""

import asyncio
import json
import socket
import ssl
import stat
from datetime import UTC, datetime, timedelta

import aiohttp
import asyncssh
import pytest

from devicevault_protocol import blobs, signing
from devicevault_protocol import identity as identity_store
from devicevault_protocol import monitoring as protocol
from devicevault_protocol.monitoring import MONITORING_EVENT_TASK
from devicevault_protocol.registration import ORCHESTRATOR_QUEUE
from devicevault_receiver import certificate as tls
from devicevault_receiver.config import ReceiverConfig
from devicevault_receiver.events import Events
from devicevault_receiver.ingest import Ingestor
from devicevault_receiver.receiver import Receiver

ORCHESTRATOR = signing.generate_signing_key()
NOW = datetime(2026, 10, 1, 12, 0, tzinfo=UTC)
SECRET = 'secret-of-zabbix'
TOKEN = f'dvt_abcd1234_{SECRET}'
DEVICES = {7: {'id': 7, 'name': 'edge-01', 'ip': '192.0.2.10', 'last_success_at': 0, 'state': 'stored'}}


def free_port() -> int:
    with socket.socket() as probe:
        probe.bind(('127.0.0.1', 0))
        return probe.getsockname()[1]


def relay_token(**overrides):
    return {
        'prefix': 'abcd1234',
        'digest': protocol.token_digest(SECRET),
        'owner': 5,
        'expires_at': (NOW + timedelta(days=30)).isoformat(),
        'allowed_networks': [],
        **overrides,
    }


def config(port=8443, *, enabled=True, rate='600/min', tokens=None):
    return ReceiverConfig.model_validate(
        {
            'bind_address': '127.0.0.1',
            'monitoring': {
                'enabled': enabled,
                'port': port,
                'rate': rate,
                'tokens': [relay_token()] if tokens is None else tokens,
            },
        }
    )


class Sent:
    def __init__(self, identity):
        self.identity = identity
        self.tasks = []

    def __call__(self, name, args=None, queue=None, **kwargs):
        self.tasks.append((name, args, queue, kwargs))

    def events(self):
        public = signing.public_key_from_b64(self.identity.signing_public_key)
        return [signing.verify(args[0], public) for _, args, _, _ in self.tasks]


@pytest.fixture
def relay_identity(tmp_path):
    identity = identity_store.load_or_create(tmp_path / 'identity.json')
    identity.pin_orchestrator(signing.public_key_to_b64(ORCHESTRATOR))
    return identity


@pytest.fixture
def relay_sent(relay_identity):
    return Sent(relay_identity)


@pytest.fixture
def receiver(redis, relay_identity, relay_sent, spool, tmp_path):
    events = Events(relay_identity, relay_sent)
    made = Receiver(
        ingestor=Ingestor(redis=redis, events=events, spool_dir=spool),
        events=events,
        host_key=asyncssh.generate_private_key('ssh-ed25519'),
        spool_dir=spool,
        certificate=tls.load_or_create(tmp_path / 'tls', hostname='receiver-test'),
    )
    made.relay._now = lambda: NOW
    return made


def publish(redis, owner=5, *, key=ORCHESTRATOR, now=NOW, devices=None):
    return protocol.publish(redis, key, owner, devices or DEVICES, {'192.0.2.10': 7}, interval=900, now=now)


def run(coroutine):
    return asyncio.run(coroutine)


# --- certificate ----------------------------------------------------------------------------


def test_the_certificate_is_generated_once_and_kept(tmp_path):
    first = tls.load_or_create(tmp_path, hostname='receiver-a')
    again = tls.load_or_create(tmp_path, hostname='another-name')

    assert first == again
    assert len(first.fingerprint.split(':')) == 32 and first.fingerprint == first.fingerprint.upper()
    assert stat.S_IMODE(first.key_path.stat().st_mode) == 0o600
    assert isinstance(first.ssl_context(), ssl.SSLContext)


def test_a_new_certificate_after_the_old_one_is_deleted(tmp_path):
    first = tls.load_or_create(tmp_path, hostname='receiver-a')
    first.certificate_path.unlink()

    assert tls.load_or_create(tmp_path, hostname='receiver-a').fingerprint != first.fingerprint


# --- configuration --------------------------------------------------------------------------


def test_the_relay_is_off_by_default_and_its_rate_must_parse():
    assert not ReceiverConfig().monitoring.enabled and ReceiverConfig().monitoring.port == 8443

    with pytest.raises(ValueError):
        config(rate='lots')
    assert config(rate='5/sec').monitoring.limit == (5, 1)


# --- tokens ---------------------------------------------------------------------------------


@pytest.mark.parametrize(
    ('header', 'address', 'tokens', 'cause'),
    [
        ('', '192.0.2.5', None, 'malformed'),
        (f'Basic {TOKEN}', '192.0.2.5', None, 'malformed'),
        ('Bearer not-a-token', '192.0.2.5', None, 'malformed'),
        ('Bearer dvt_zzzz9999_secret', '192.0.2.5', None, 'unknown'),
        ('Bearer dvt_abcd1234_wrong-secret', '192.0.2.5', None, 'unknown'),
        (f'Bearer {TOKEN}', '192.0.2.5', [relay_token(expires_at=NOW.isoformat())], 'expired'),
        (f'Bearer {TOKEN}', '198.51.100.1', [relay_token(allowed_networks=['192.0.2.0/24'])], 'network'),
        (f'Bearer {TOKEN}', '', [relay_token(allowed_networks=['192.0.2.0/24'])], 'network'),
    ],
)
def test_refused_tokens_and_why(receiver, header, address, tokens, cause):
    receiver.config = config(tokens=tokens)

    token, _, refused_for = receiver.relay.check(header, address, NOW)

    assert token is None and refused_for == cause


def test_an_assigned_token_from_an_allowed_network_is_accepted(receiver):
    receiver.config = config(tokens=[relay_token(allowed_networks=['192.0.2.0/24', '2001:db8::/32'])])

    for address in ('192.0.2.5', '2001:db8::5'):
        token, prefix, cause = receiver.relay.check(f'bearer  {TOKEN} ', address, NOW)
        assert (token.owner, prefix, cause) == (5, 'abcd1234', '')


def test_each_token_is_rate_limited_per_window(receiver):
    receiver.config = config(rate='2/min')
    relay = receiver.relay

    assert [relay.over_rate('abcd1234', at=60.0) for _ in range(3)] == [False, False, True]
    assert relay.over_rate('other', at=60.0) is False
    assert relay.over_rate('abcd1234', at=121.0) is False  # a new window


# --- snapshots ------------------------------------------------------------------------------


def test_a_published_snapshot_is_loaded_and_served(receiver, redis):
    receiver.config = config()
    publish(redis)

    run(receiver.relay.refresh())
    token, _, _ = receiver.relay.check(f'Bearer {TOKEN}', '192.0.2.5', NOW)
    snapshot = receiver.relay.snapshots[5]

    for ip, device_id in (('192.0.2.10', ''), ('::ffff:192.0.2.10', ''), ('', '7'), ('192.0.2.99', '')):
        status, body = receiver.relay.answer(token, ip=ip, device_id=device_id, now=NOW)
        assert status == 200
        assert body == protocol.device_response(snapshot, ip=ip, device_id=device_id, now=NOW)
    assert receiver.relay.answer(token, ip='192.0.2.10', device_id='', now=NOW)[1]['found'] == 1
    assert receiver.relay.answer(token, ip='192.0.2.99', device_id='', now=NOW)[1]['found'] == 0


def test_without_a_current_snapshot_the_relay_answers_stale(receiver, redis):
    receiver.config = config()
    token, _, _ = receiver.relay.check(f'Bearer {TOKEN}', '192.0.2.5', NOW)

    assert receiver.relay.answer(token, ip='192.0.2.10', device_id='', now=NOW) == (503, {'error': 'stale'})

    publish(redis, now=NOW - timedelta(seconds=3 * 900 + 1))
    run(receiver.relay.refresh())
    assert 5 in receiver.relay.snapshots
    assert receiver.relay.answer(token, ip='192.0.2.10', device_id='', now=NOW) == (503, {'error': 'stale'})


def test_an_unchanged_generation_is_not_fetched_again(receiver, redis, monkeypatch):
    receiver.config = config()
    publish(redis)
    run(receiver.relay.refresh())
    fetched = []
    monkeypatch.setattr(blobs, 'get', lambda *args: fetched.append(args))

    run(receiver.relay.refresh())

    assert fetched == []


def test_a_forged_snapshot_is_ignored_and_reported_once(receiver, redis, relay_sent):
    receiver.config = config()
    publish(redis)
    run(receiver.relay.refresh())
    loaded = receiver.relay.snapshots[5]

    publish(redis, key=signing.generate_signing_key(), now=NOW + timedelta(minutes=15))
    run(receiver.relay.refresh())
    run(receiver.relay.refresh())

    assert receiver.relay.snapshots[5] is loaded
    rejected = [e for e in relay_sent.events() if e['event'] == protocol.EVENT_SNAPSHOT_REJECTED]
    assert len(rejected) == 1 and rejected[0]['owner'] == 5 and 'pointer' in rejected[0]['reason']
    assert relay_sent.tasks[0][0] == MONITORING_EVENT_TASK and relay_sent.tasks[0][2] == ORCHESTRATOR_QUEUE


def test_a_blob_that_does_not_match_its_pointer_is_ignored(receiver, redis, relay_sent):
    receiver.config = config()
    pointer = publish(redis)
    document = json.loads(blobs.get(redis, pointer['blob']['key']))
    document['devices']['7']['state'] = 'failed'
    blobs.put(redis, pointer['blob']['key'], json.dumps(document).encode(), 900)

    run(receiver.relay.refresh())

    assert 5 not in receiver.relay.snapshots
    [event] = relay_sent.events()
    assert event['event'] == protocol.EVENT_SNAPSHOT_REJECTED and event['generation'] == pointer['generation']
    assert receiver.relay.status()['snapshots'] == {}


def test_only_owners_with_assigned_tokens_are_loaded(receiver, redis):
    receiver.config = config()
    publish(redis)
    publish(redis, owner=6)

    run(receiver.relay.refresh())

    assert set(receiver.relay.snapshots) == {5}


# --- over HTTPS -----------------------------------------------------------------------------


def test_requests_over_https(receiver, redis, relay_sent):
    port = free_port()
    publish(redis)

    async def scenario():
        await receiver.apply(config(port))
        await receiver.relay.refresh()
        base = f'https://127.0.0.1:{port}'
        good = {'Authorization': f'Bearer {TOKEN}'}
        try:
            async with aiohttp.ClientSession(connector=aiohttp.TCPConnector(ssl=False)) as http:
                answers = []
                for path, headers in (
                    ('/device/?ip=192.0.2.10', good),
                    ('/api/monitoring/device/?id=7', good),
                    ('/device/?ip=192.0.2.10', {}),
                    ('/device/?ip=192.0.2.10', {'Authorization': 'Bearer dvt_abcd1234_wrong'}),
                ):
                    async with http.get(base + path, headers=headers) as answer:
                        answers.append((answer.status, await answer.json()))
                status = receiver.status()['monitoring']
            await asyncio.sleep(0.1)  # the refusal is sent from a thread
            await receiver.relay.flush()
            return answers, status
        finally:
            await receiver.close()

    answers, status = run(scenario())

    assert [code for code, _ in answers] == [200, 200, 401, 401]
    assert answers[0][1]['found'] == 1 and answers[1][1]['name'] == 'edge-01'
    assert answers[2][1] == answers[3][1] == {'detail': 'Invalid or expired token.'}
    assert status['listening'] and status['port'] == port and status['error'] == ''
    assert status['certificate_fingerprint'] == receiver.certificate.fingerprint
    assert (status['requests'], status['refused'], status['tokens']) == (2, 2, 1)
    assert status['snapshots']['5']['devices'] == 1 and not status['snapshots']['5']['stale']

    events = relay_sent.events()
    refused = [e for e in events if e['event'] == protocol.EVENT_REFUSED]
    assert [(e['source_ip'], e['cause']) for e in refused] == [('127.0.0.1', 'malformed')]  # once per address
    [used] = [e for e in events if e['event'] == protocol.EVENT_USED]
    assert used['tokens'] == [
        {'prefix': 'abcd1234', 'requests': 2, 'addresses': ['127.0.0.1'], 'last_used_at': NOW.isoformat()}
    ]


def test_over_the_rate_a_token_gets_429(receiver, redis):
    port = free_port()
    publish(redis)

    async def scenario():
        await receiver.apply(config(port, rate='1/hour'))
        await receiver.relay.refresh()
        try:
            async with aiohttp.ClientSession(connector=aiohttp.TCPConnector(ssl=False)) as http:
                codes = []
                for _ in range(2):
                    async with http.get(
                        f'https://127.0.0.1:{port}/device/?id=7', headers={'Authorization': f'Bearer {TOKEN}'}
                    ) as answer:
                        codes.append(answer.status)
                return codes
        finally:
            await receiver.close()

    assert run(scenario()) == [200, 429]
    assert receiver.relay.throttled == 1


def test_the_port_is_open_only_while_enabled(receiver):
    port = free_port()

    async def scenario():
        await receiver.apply(config(port))
        listening = receiver.relay.bound
        await receiver.apply(config(port, enabled=False))
        closed = receiver.relay.bound
        try:
            await asyncio.open_connection('127.0.0.1', port)
            refused = False
        except OSError:
            refused = True
        await receiver.close()
        return listening, closed, refused

    listening, closed, refused = run(scenario())

    assert listening == ('127.0.0.1', port) and closed is None and refused
    assert receiver.relay.status()['listening'] is False


def test_a_port_in_use_is_reported(receiver):
    with socket.socket() as taken:
        taken.bind(('127.0.0.1', 0))
        taken.listen()
        port = taken.getsockname()[1]

        async def scenario():
            await receiver.apply(config(port))
            status = receiver.status()['monitoring']
            await receiver.close()
            return status

        status = run(scenario())

    assert not status['listening'] and 'cannot listen' in status['error']
