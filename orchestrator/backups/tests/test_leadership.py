"""Two orchestrator nodes sharing the scheduler lease."""

from datetime import UTC, datetime

import fakeredis
import pytest

from backups.models import BackupJob
from backups.scheduler import LEASE_KEY, Leadership, run_due_schedules


@pytest.fixture
def redis():
    return fakeredis.FakeRedis()


@pytest.fixture
def nodes(redis):
    return Leadership(redis, node='node-a'), Leadership(redis, node='node-b')


def test_one_node_leads_and_keeps_the_lease(redis, nodes):
    a, b = nodes
    assert a.acquire_or_renew()
    assert not b.acquire_or_renew()
    assert a.acquire_or_renew()
    assert not b.acquire_or_renew()
    assert redis.get(LEASE_KEY) == a.token.encode()
    assert 0 < redis.pttl(LEASE_KEY) <= a.lease_seconds * 1000


def test_the_standby_takes_over_when_the_leader_stops(nodes):
    a, b = nodes
    a.acquire_or_renew()
    a.release()
    assert b.acquire_or_renew()
    assert not a.acquire_or_renew()


def test_the_standby_takes_over_when_the_lease_expires(redis, nodes):
    a, b = nodes
    a.acquire_or_renew()
    redis.delete(LEASE_KEY)  # what expiry does once a crashed leader stops renewing
    assert b.acquire_or_renew()
    # The old leader, back from a stall, neither extends nor releases b's lease.
    assert not a.acquire_or_renew()
    a.release()
    assert redis.get(LEASE_KEY) == b.token.encode()


def test_the_lease_lasts_as_long_as_asked(redis):
    node = Leadership(redis, lease_seconds=120)
    node.acquire_or_renew()
    assert 60_000 < redis.pttl(LEASE_KEY) <= 120_000


def test_a_leader_that_lost_the_lease_schedules_nothing(nightly, broker):
    late = datetime(2026, 10, 24, 15, 30, tzinfo=UTC)
    assert run_due_schedules(late, leading=lambda: False) == 0
    assert not BackupJob.objects.exists()
    nightly.refresh_from_db()
    assert nightly.last_run_at is None

    assert run_due_schedules(late, leading=lambda: True) == 1
