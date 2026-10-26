import json
from datetime import timedelta

import pytest
from django.utils import timezone
from rest_framework.test import APIClient

from backups.models import BackupJob
from devices.models import Device, DeviceGroup
from devicevault_protocol import jobs
from devicevault_protocol import monitoring as protocol
from monitoring import catalogue, metrics, snapshots
from monitoring.catalogue import code


@pytest.fixture
def other_device(setup):
    return Device.objects.create(
        name='Branch 02',
        device_type=setup['device'].device_type,
        ip_address='192.0.2.20',
        device_group=DeviceGroup.objects.create(name='Branches'),
        collection_group=setup['group'],
        storage_target=setup['target'],
        backup_method='noop',
    )


@pytest.fixture
def zabbix(setup, service_account, make_token, token_client):
    """A service account seeing the Core group, with a monitoring token: (user, client)."""
    account = service_account(groups=[setup['device'].device_group])
    _, raw = make_token(account, scopes=['monitoring'])
    return account, token_client(raw)


def estate_keys(platform=False):
    keys = catalogue.keys(catalogue.ESTATE)
    return set(keys) | (set(catalogue.keys(catalogue.PLATFORM)) if platform else set())


# --- summary and groups ------------------------------------------------------------------


def test_summary_counts_outcomes_ratios_and_reasons(job, zabbix):
    job(took=timedelta(seconds=10), collect_duration_ms=4000, store_duration_ms=1000, changed=True, lines_added=3)
    job(took=timedelta(seconds=30), collect_duration_ms=6000, store_duration_ms=1000)
    job(BackupJob.FAILED, failure_reason=jobs.FAILURE_AUTH)
    job(BackupJob.TIMED_OUT, failure_reason=jobs.FAILURE_ORPHANED, ago=timedelta(hours=2))
    job(BackupJob.FAILED, ago=timedelta(days=3))  # no reason: recorded before reasons existed
    job(BackupJob.QUEUED)

    figures = zabbix[1].get('/api/monitoring/summary/').json()

    assert (figures['stored_1h'], figures['failed_1h'], figures['timed_out_24h']) == (2, 1, 1)
    assert figures['finished_24h'] == 4 and figures['success_ratio_24h'] == 50.0
    assert figures['failure_ratio_7d'] == 60.0 and figures['failed_total'] == 2
    assert figures['failures_auth_24h'] == 1 and figures['failures_orphaned_24h'] == 1
    assert figures['failures_unknown_total'] == 1
    assert figures['queued'] == 1 and figures['running'] == 0
    assert figures['duration_collect_avg'] == 5.0 and figures['duration_total_max'] == 30.0
    assert figures['changed_24h'] == 1 and figures['lines_added_24h'] == 3
    assert figures['devices_total'] == 1 and figures['devices_failing_1'] == 1
    assert figures['backups_held'] == 2


def test_figures_have_exactly_the_catalogue_keys(job, zabbix, admin_client):
    job()

    as_token = zabbix[1].get('/api/monitoring/summary/').json()
    as_admin = admin_client.get('/api/monitoring/summary/').json()
    group = zabbix[1].get('/api/monitoring/device-groups/').json()['data'][0]

    assert set(as_token) == estate_keys()
    assert set(as_admin) == estate_keys(platform=True)
    assert set(group) == set(catalogue.keys(catalogue.GROUP))
    for path, scope in [('workers', catalogue.WORKER), ('storage-targets', catalogue.TARGET)]:
        entries = admin_client.get(f'/api/monitoring/{path}/').json()['data']
        assert entries and all(set(entry) == set(catalogue.keys(scope)) for entry in entries)


def test_a_token_sees_only_its_owners_devices(job, zabbix, other_device):
    job()
    job(device=other_device)
    job(BackupJob.FAILED, device=other_device)

    figures = zabbix[1].get('/api/monitoring/summary/').json()
    groups = zabbix[1].get('/api/monitoring/device-groups/').json()['data']

    assert figures['stored_24h'] == 1 and figures['failed_24h'] == 0
    assert [group['name'] for group in groups] == ['Core']


def test_platform_sections_need_the_platform_scope(setup, service_account, make_token, token_client):
    account = service_account(groups=[setup['device'].device_group])
    _, plain = make_token(account, scopes=['monitoring'], name='plain')
    _, platform = make_token(account, scopes=['monitoring_platform'], name='platform')

    assert token_client(plain).get('/api/monitoring/workers/').json() == {'data': []}
    workers = token_client(platform).get('/api/monitoring/workers/').json()['data']
    assert {row['name'] for row in workers} == {'collector-1', 'storage-1'}
    summary = token_client(platform).get('/api/monitoring/summary/').json()
    assert summary['workers_pending'] == 0 and summary['scheduler_leader'] == 0


def test_monitoring_is_read_only_and_needs_signing_in(db, zabbix):
    assert APIClient().get('/api/monitoring/summary/').status_code == 401
    assert zabbix[1].post('/api/monitoring/summary/').status_code in (403, 405)


def test_figures_are_cached_briefly(job, zabbix):
    first = zabbix[1].get('/api/monitoring/summary/').json()
    job()
    second = zabbix[1].get('/api/monitoring/summary/').json()

    assert first['stored_24h'] == second['stored_24h'] == 0
    assert second['computed_age'] >= 0


def test_groups_without_devices_have_zero_counts_and_no_ratios(setup, admin_client):
    DeviceGroup.objects.create(name='Empty')

    groups = {row['name']: row for row in admin_client.get('/api/monitoring/device-groups/').json()['data']}

    assert groups['Empty']['stored_24h'] == 0 and groups['Empty']['success_ratio_24h'] is None


# --- devices and relay snapshots ---------------------------------------------------------


def test_device_rows_describe_the_latest_backups(job, setup):
    job(ago=timedelta(hours=5), size_bytes=1200, changed=True, lines_added=4, collect_duration_ms=2500)
    job(BackupJob.FAILED, ago=timedelta(hours=2), failure_reason=jobs.FAILURE_AUTH)
    job(BackupJob.FAILED, ago=timedelta(hours=1), failure_reason=jobs.FAILURE_TIMEOUT)

    rows, by_ip = metrics.device_rows(Device.objects.all())
    row = rows[setup['device'].pk]

    assert by_ip == {'192.0.2.10': setup['device'].pk}
    assert set(row) | {'found', 'last_success_age', 'published_at', 'published_age'} == set(
        catalogue.keys(catalogue.DEVICE)
    )
    assert row['status_code'] == code('job_status', 'failed')
    assert row['failure_reason_code'] == code('failure_reason', jobs.FAILURE_TIMEOUT)
    assert row['consecutive_failures'] == 2
    assert row['last_size'] == 1200 and row['last_changed'] == 1 and row['last_lines_added'] == 4
    assert row['last_collect_duration'] == 2.5 and row['backups_held'] == 1
    assert row['success_ratio_7d'] == pytest.approx(33.33)
    assert row['lifecycle_code'] == code('lifecycle', 'active')


def test_relay_owners_are_service_accounts_with_monitoring_tokens(setup, service_account, make_token, make_user):
    zabbix = service_account('zabbix')
    scripts = service_account('scripts')
    person = make_user('person')
    make_token(zabbix, scopes=['monitoring'])
    make_token(scripts, scopes=['api'])
    make_token(person, scopes=['monitoring'])

    assert snapshots.relay_owners() == [zabbix]


def test_the_device_endpoint_answers_from_the_published_snapshot(job, zabbix, other_device):
    job()
    account, client = zabbix
    assert snapshots.publish_relays() == 1

    by_ip = client.get('/api/monitoring/device/?ip=192.0.2.10').json()
    by_id = client.get(f'/api/monitoring/device/?ip=198.51.100.1&id={by_ip["id"]}').json()
    hidden = client.get('/api/monitoring/device/?ip=192.0.2.20').json()

    assert by_ip['found'] == 1 and by_ip['name'] == 'Edge 01' and by_ip['last_success_age'] >= 0
    assert by_id['id'] == by_ip['id']
    assert hidden['found'] == 0 and set(hidden) == {'found', 'published_at', 'published_age'}


def test_the_device_endpoint_is_stale_without_a_current_snapshot(zabbix, token_redis):
    account, client = zabbix

    assert client.get('/api/monitoring/device/?ip=192.0.2.10').status_code == 503

    snapshots.publish_relays(now=timezone.now() - timedelta(hours=2))
    assert client.get('/api/monitoring/device/?ip=192.0.2.10').json() == {'error': 'stale'}


def test_a_forged_snapshot_is_refused(zabbix, token_redis):
    from devicevault_protocol import signing

    account, client = zabbix
    snapshots.publish_relays()
    forger = signing.generate_signing_key()
    protocol.publish(token_redis, forger, account.pk, {}, {}, interval=900)

    assert client.get('/api/monitoring/device/?ip=192.0.2.10').status_code == 503


def test_only_service_accounts_have_device_snapshots(setup, make_user, make_token, token_client):
    _, raw = make_token(make_user('person', grants={setup['device'].device_group: ['view']}), scopes=['monitoring'])

    assert token_client(raw).get('/api/monitoring/device/?ip=192.0.2.10').status_code == 404


def test_the_scheduler_publishes_snapshots_and_records_its_tick(zabbix, token_redis, monkeypatch):
    from backups import scheduler

    monkeypatch.setattr(scheduler, 'catch_up', lambda now: 0)
    scheduler.tick()
    scheduler.tick()  # not due again yet

    pointer = json.loads(token_redis.get(protocol.pointer_key(zabbix[0].pk)))
    assert pointer['payload']['owner'] == zabbix[0].pk
    assert token_redis.get(metrics.TICK_KEY) is not None


# --- Prometheus --------------------------------------------------------------------------


def test_prometheus_exposition(job, admin_client):
    job()
    job(BackupJob.FAILED, failure_reason=jobs.FAILURE_AUTH)

    answer = admin_client.get('/api/monitoring/metrics', HTTP_ACCEPT='text/plain;version=0.0.4')
    body = answer.content.decode()

    assert answer.status_code == 200 and answer['Content-Type'].startswith('text/plain')
    assert '# TYPE devicevault_backups_finished_total counter' in body
    assert 'devicevault_backups_finished{state="stored",window="24h"} 1' in body
    assert 'devicevault_group_backups_finished{device_group="Core",state="failed",window="24h"} 1' in body
    assert 'devicevault_backup_failures{reason="auth",window="24h"} 1' in body
    assert 'devicevault_worker_online{worker="collector-1"}' in body
    assert 'Edge 01' not in body  # no per-device series


def test_the_shipped_alert_rules_use_real_series():
    import re
    from pathlib import Path

    from monitoring.prometheus import _family

    rules = Path(__file__).resolve().parents[3] / 'deploy' / 'prometheus' / 'devicevault-rules.yml'
    used = set(re.findall(r'\b(devicevault_[a-z_]+)\b', rules.read_text()))
    known = {
        _family(metric.prometheus, metric.scope) for metric in catalogue.CATALOGUE if metric.prometheus is not None
    }

    assert used - known == set()
