"""Receiver monitoring relays: their settings, the tokens in their assignments, and the events they send."""

from datetime import UTC, datetime, timedelta

import pytest
from django.utils import timezone

from accounts.models import ApiToken
from audit.models import AuditLog
from core.models import Worker
from devicevault_protocol import monitoring as protocol
from devicevault_protocol import signing
from monitoring import relay, snapshots
from push.events import EventRejected
from push.service import settings_for


def section(published, worker):
    envelope = [e for worker_id, e in published if worker_id == str(worker.pk)][-1]
    return signing.peek(envelope)['receiver']['monitoring']


def enable_relay(worker, **fields):
    receiver_settings = settings_for(worker)
    receiver_settings.monitoring_enabled = True
    for field, value in fields.items():
        setattr(receiver_settings, field, value)
    receiver_settings.save()


def version(worker) -> int:
    return Worker.objects.get(pk=worker.pk).desired_version


def event(keys, name, **details):
    payload = {'event': name, 'worker_id': keys.id, 'at': datetime.now(UTC).isoformat(), **details}
    return signing.sign(payload, keys.key, keys.id)


# --- the assignment ------------------------------------------------------------------------


def test_the_assignment_carries_relay_tokens_as_digests(
    receiver, published, service_account, make_user, make_token, settings
):
    from core.workers import update_assignment

    _, worker = receiver
    settings.DEVICEVAULT_API_TOKEN_RATE = '120/min'
    zabbix = service_account('zabbix')
    relay_token, raw = make_token(zabbix, ('monitoring',), name='zbx', allowed_networks=['192.0.2.0/24'])
    make_token(zabbix, ('api',), name='api only')
    revoked, _ = make_token(zabbix, ('monitoring',), name='revoked')
    ApiToken.objects.filter(pk=revoked.pk).update(revoked_at=timezone.now())
    make_token(make_user('person'), ('monitoring',), name='a person')  # people own no snapshots
    inactive = service_account('retired')
    inactive.is_active = False
    inactive.save()
    make_token(inactive, ('monitoring',), name='inactive')
    expired, _ = make_token(service_account('old'), ('monitoring_platform',), name='expired')
    ApiToken.objects.filter(pk=expired.pk).update(expires_at=timezone.now() - timedelta(minutes=1))

    update_assignment(worker)
    assert section(published, worker) == {'enabled': False, 'port': 8443, 'rate': '120/min', 'tokens': []}

    enable_relay(worker, monitoring_port=9443)
    update_assignment(worker)
    monitoring = section(published, worker)

    assert (monitoring['enabled'], monitoring['port'], monitoring['rate']) == (True, 9443, '120/min')
    assert monitoring['tokens'] == [
        {
            'prefix': relay_token.prefix,
            'digest': relay_token.digest,
            'owner': zabbix.pk,
            'expires_at': relay_token.expires_at.isoformat(),
            'allowed_networks': ['192.0.2.0/24'],
        }
    ]
    assert raw.split('_', 2)[2] not in str(published[-1][1])  # never the secret


def test_creating_and_revoking_a_relay_token_resends_assignments(
    receiver, admin_client, service_account, token_redis, django_capture_on_commit_callbacks
):
    _, worker = receiver
    zabbix = service_account('zabbix')
    start = version(worker)

    with django_capture_on_commit_callbacks(execute=True):
        created = admin_client.post(
            f'/api/service-accounts/{zabbix.pk}/tokens/', {'name': 'zbx', 'scopes': ['monitoring']}, format='json'
        )
    assert created.status_code == 201, created.content
    assert version(worker) == start + 1
    assert token_redis.get(snapshots.PUBLISH_NOW_KEY) is not None  # a snapshot for the new owner soon

    with django_capture_on_commit_callbacks(execute=True):
        admin_client.post(f'/api/service-accounts/{zabbix.pk}/tokens/', {'name': 'api', 'scopes': ['api']})
    assert version(worker) == start + 1  # not a relay token

    with django_capture_on_commit_callbacks(execute=True):
        assert admin_client.post(f'/api/admin/tokens/{created.json()["id"]}/revoke/').status_code == 204
    assert version(worker) == start + 2


def test_a_personal_monitoring_token_does_not_concern_receivers(
    receiver, make_user, client_for, django_capture_on_commit_callbacks
):
    _, worker = receiver
    start = version(worker)

    with django_capture_on_commit_callbacks(execute=True):
        answer = client_for(make_user('person')).post(
            '/api/tokens/', {'name': 'mine', 'scopes': ['monitoring']}, format='json'
        )

    assert answer.status_code == 201 and version(worker) == start


def test_changing_or_deleting_a_service_account_resends_assignments(
    receiver, admin_client, service_account, django_capture_on_commit_callbacks
):
    _, worker = receiver
    zabbix = service_account('zabbix')
    start = version(worker)

    with django_capture_on_commit_callbacks(execute=True):
        answer = admin_client.patch(f'/api/service-accounts/{zabbix.pk}/', {'is_active': False}, format='json')
    assert answer.status_code == 200, answer.content
    assert version(worker) == start + 1

    with django_capture_on_commit_callbacks(execute=True):
        assert admin_client.delete(f'/api/service-accounts/{zabbix.pk}/').status_code == 204
    assert version(worker) == start + 2


def test_a_relay_token_reaching_its_expiry_resends_assignments(
    receiver, service_account, make_token, monkeypatch, django_capture_on_commit_callbacks
):
    _, worker = receiver
    monkeypatch.setattr(relay, '_last_expiry_check', None)
    token, _ = make_token(service_account('zabbix'), ('monitoring',), days=1)
    now = timezone.now()
    start = version(worker)

    with django_capture_on_commit_callbacks(execute=True):
        assert relay.expire_relay_tokens(now) is False  # the first tick only notes the time
        assert relay.expire_relay_tokens(now + timedelta(hours=1)) is False
        assert relay.expire_relay_tokens(token.expires_at + timedelta(seconds=1)) is True
        assert relay.expire_relay_tokens(token.expires_at + timedelta(minutes=1)) is False
    assert version(worker) == start + 1


def test_a_requested_publish_runs_before_the_interval(service_account, make_token, token_redis):
    make_token(service_account('zabbix'), ('monitoring',))
    now = timezone.now()

    assert snapshots.publish_if_due(now) == 1
    assert snapshots.publish_if_due(now + timedelta(seconds=30)) is None
    snapshots.request_publish()
    assert snapshots.publish_if_due(now + timedelta(seconds=60)) == 1
    assert snapshots.publish_if_due(now + timedelta(seconds=90)) is None


# --- settings ----------------------------------------------------------------------------


def test_relay_settings_round_trip(receiver, admin_client, published):
    _, worker = receiver
    url = f'/api/workers/{worker.pk}/receiver/'

    before = admin_client.get(url).json()
    assert (before['monitoring_enabled'], before['monitoring_port']) == (False, 8443)
    answer = admin_client.patch(url, {'monitoring_enabled': True, 'monitoring_port': 9443}, format='json')

    assert answer.status_code == 200, answer.content
    assert section(published, worker)['enabled'] is True and section(published, worker)['port'] == 9443
    entry = AuditLog.objects.filter(action='receiver.update').latest('created_at')
    assert entry.details['monitoring_enabled'] is True


@pytest.mark.parametrize(
    ('body', 'ok'),
    [
        ({'monitoring_enabled': True, 'monitoring_port': 0}, False),
        ({'monitoring_enabled': True, 'monitoring_port': 65536}, False),
        ({'monitoring_enabled': True, 'ssh_enabled': True, 'ssh_password': 'pw', 'ssh_port': 8443}, False),
        ({'monitoring_enabled': True, 'tftp_enabled': True, 'tftp_port': 8443}, True),  # UDP
        ({'monitoring_enabled': False, 'ssh_enabled': True, 'ssh_password': 'pw', 'ssh_port': 8443}, True),
    ],
)
def test_relay_settings_are_validated(receiver, admin_client, body, ok):
    _, worker = receiver

    answer = admin_client.patch(f'/api/workers/{worker.pk}/receiver/', body, format='json')

    assert (answer.status_code == 200) is ok, answer.content


# --- events from relays ----------------------------------------------------------------------


def test_use_reported_by_a_relay_updates_the_token_and_audits_new_addresses(receiver, service_account, make_token):
    keys, worker = receiver
    token, _ = make_token(service_account('zabbix'), ('monitoring',))
    at = timezone.now() - timedelta(seconds=30)
    entry = {'prefix': token.prefix, 'requests': 3, 'addresses': ['192.0.2.5', '::ffff:192.0.2.6', 'junk']}

    assert (
        relay.handle_monitoring_event(
            event(keys, protocol.EVENT_USED, tokens=[entry | {'last_used_at': at.isoformat()}])
        )
        == 1
    )
    relay.handle_monitoring_event(event(keys, protocol.EVENT_USED, tokens=[entry]))

    token.refresh_from_db()
    assert token.addresses == ['192.0.2.5', '192.0.2.6']
    assert token.last_used_address == '192.0.2.6' and token.last_used_at >= at
    uses = AuditLog.objects.filter(action='token.use').order_by('pk')
    assert [(u.details['address'], u.details['receiver'], u.actor_name) for u in uses] == [
        ('192.0.2.5', worker.name, 'zabbix'),
        ('192.0.2.6', worker.name, 'zabbix'),
    ]


def test_use_of_a_token_relays_were_never_given_is_ignored(receiver, make_user, make_token):
    keys, _ = receiver
    personal, _ = make_token(make_user('person'), ('monitoring',))
    entries = [{'prefix': personal.prefix, 'addresses': ['192.0.2.5']}, {'prefix': 'nonesuch', 'addresses': []}]

    assert relay.handle_monitoring_event(event(keys, protocol.EVENT_USED, tokens=entries)) == 0
    assert not AuditLog.objects.filter(action='token.use').exists()


def test_a_refusal_reported_by_a_relay_is_audited_naming_the_receiver(receiver):
    keys, worker = receiver
    refused = event(keys, protocol.EVENT_REFUSED, source_ip='192.0.2.5', prefix='abcd1234', cause='network')

    relay.handle_monitoring_event(refused)
    relay.handle_monitoring_event(refused)  # within a minute from the same address
    relay.handle_monitoring_event(event(keys, protocol.EVENT_REFUSED, source_ip='192.0.2.6', cause='made-up'))

    entries = AuditLog.objects.filter(action='token.refused').order_by('pk')
    assert [(e.details['address'], e.details['cause'], e.details['receiver']) for e in entries] == [
        ('192.0.2.5', 'network', worker.name),
        ('192.0.2.6', 'unknown', worker.name),
    ]
    assert entries[0].resource == 'abcd1234' and entries[0].outcome == AuditLog.DENIED


def test_a_rejected_snapshot_is_audited(receiver):
    keys, worker = receiver

    relay.handle_monitoring_event(
        event(keys, protocol.EVENT_SNAPSHOT_REJECTED, owner=5, generation='abc', reason='pointer: bad signature')
    )

    entry = AuditLog.objects.get(action='monitoring.snapshot_rejected')
    assert entry.outcome == AuditLog.FAILURE and entry.actor_name == worker.name
    assert entry.details == {
        'receiver': worker.name,
        'owner': 5,
        'generation': 'abc',
        'reason': 'pointer: bad signature',
    }


def test_events_must_come_signed_from_an_approved_receiver(receiver, approved_collector, worker_keys):
    from core import workers

    keys, worker = receiver
    stranger = worker_keys('stranger')
    pending = workers.handle_event(stranger.event())
    refused = {'source_ip': '192.0.2.5', 'cause': 'unknown'}

    forged = event(keys, protocol.EVENT_REFUSED, **refused)
    forged['sig'] = event(stranger, protocol.EVENT_REFUSED, **refused)['sig']
    for envelope in (forged, event(stranger, protocol.EVENT_REFUSED, **refused)):
        with pytest.raises(EventRejected):
            relay.handle_monitoring_event(envelope)
    assert pending.status == 'pending'

    workers.revoke(worker)
    with pytest.raises(EventRejected):
        relay.handle_monitoring_event(event(keys, protocol.EVENT_REFUSED, **refused))
    assert not AuditLog.objects.filter(action='token.refused').exists()


def test_the_events_task_swallows_rejected_events(receiver, worker_keys):
    from core.tasks import monitoring_event

    stranger = worker_keys('stranger')

    monitoring_event(event(stranger, protocol.EVENT_REFUSED, source_ip='192.0.2.5', cause='unknown'))

    assert not AuditLog.objects.filter(action='token.refused').exists()
