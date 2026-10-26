import json
from datetime import UTC, datetime, timedelta

import fakeredis
import pytest

from devicevault_protocol import blobs, monitoring, signing

KEY = signing.generate_signing_key()
NOW = datetime(2026, 10, 1, 12, 0, tzinfo=UTC)
ROWS = {
    7: {'id': 7, 'name': 'edge-01', 'last_success_at': int((NOW - timedelta(hours=2)).timestamp())},
    8: {'id': 8, 'name': 'core-01', 'last_success_at': None},
}
BY_IP = {'192.0.2.10': 7, '2001:db8::8': 8}


@pytest.fixture
def redis():
    return fakeredis.FakeRedis()


def publish(redis, owner=5, key=KEY, now=NOW):
    return monitoring.publish(redis, key, owner, ROWS, BY_IP, interval=900, now=now)


# --- tokens ------------------------------------------------------------------------------


def test_token_strings_parse_into_prefix_and_secret():
    assert monitoring.parse_token('dvt_abcd1234_s3cr_et') == ('abcd1234', 's3cr_et')
    for raw in ('', 'dvt_abcd1234_', 'dvt_short_secret', 'xyz_abcd1234_secret', 'dvt_abcd1234'):
        assert monitoring.parse_token(raw) is None
    assert monitoring.token_digest('s') == monitoring.token_digest('s') != monitoring.token_digest('t')
    assert len(monitoring.token_digest('s')) == 64


def test_rates_parse():
    assert monitoring.parse_rate('600/min') == (600, 60)
    assert monitoring.parse_rate('5/sec') == (5, 1)
    assert monitoring.parse_rate('100/hour') == (100, 3600)
    for bad in ('600', '600/day', 'x/min', '0/min', '1/min/2'):
        with pytest.raises(ValueError):
            monitoring.parse_rate(bad)


# --- snapshots ---------------------------------------------------------------------------


def test_a_published_snapshot_loads_back(redis):
    pointer = publish(redis)

    snapshot = monitoring.load(redis, 5, KEY.public_key())

    assert snapshot.owner == 5 and snapshot.generation == pointer['generation'] and snapshot.interval == 900
    assert snapshot.published_at == NOW and snapshot.by_ip == BY_IP
    assert snapshot.devices['7']['name'] == 'edge-01'
    assert monitoring.read_pointer(redis, 5, KEY.public_key())['blob']['key'] == monitoring.blob_key(
        5, pointer['generation']
    )
    assert redis.ttl(monitoring.pointer_key(5)) <= 3 * 900


def test_nothing_published_is_none(redis):
    assert monitoring.load(redis, 5, KEY.public_key()) is None
    assert monitoring.read_pointer(redis, 5, KEY.public_key()) is None


def test_a_pointer_signed_by_another_key_is_refused(redis):
    publish(redis, key=signing.generate_signing_key())

    with pytest.raises(monitoring.SnapshotError, match='pointer'):
        monitoring.load(redis, 5, KEY.public_key())


def test_a_pointer_for_another_owner_is_refused(redis):
    publish(redis, owner=6)
    redis.set(monitoring.pointer_key(5), redis.get(monitoring.pointer_key(6)))

    with pytest.raises(monitoring.SnapshotError, match='another owner'):
        monitoring.read_pointer(redis, 5, KEY.public_key())


def test_a_blob_that_does_not_match_its_hash_is_refused(redis):
    pointer = publish(redis)
    document = json.loads(blobs.get(redis, pointer['blob']['key']))
    document['by_ip']['192.0.2.10'] = 8
    blobs.put(redis, pointer['blob']['key'], json.dumps(document).encode(), 900)

    with pytest.raises(monitoring.SnapshotError, match='does not match'):
        monitoring.load(redis, 5, KEY.public_key())


def test_a_missing_blob_is_none(redis):
    pointer = publish(redis)
    blobs.delete(redis, pointer['blob']['key'])

    assert monitoring.load(redis, 5, KEY.public_key()) is None


def test_snapshots_go_stale_after_three_intervals(redis):
    publish(redis)
    snapshot = monitoring.load(redis, 5, KEY.public_key())

    assert not snapshot.stale(NOW + timedelta(seconds=3 * 900))
    assert snapshot.stale(NOW + timedelta(seconds=3 * 900 + 1))


# --- answers -----------------------------------------------------------------------------


def snapshot(redis):
    publish(redis)
    return monitoring.load(redis, 5, KEY.public_key())


def test_a_device_is_found_by_address_or_id(redis):
    later = NOW + timedelta(minutes=10)
    current = snapshot(redis)

    by_ip = monitoring.device_response(current, ip=' 192.0.2.10 ', now=later)
    by_mapped = monitoring.device_response(current, ip='::ffff:192.0.2.10', now=later)
    by_v6 = monitoring.device_response(current, ip='2001:DB8::8', now=later)
    by_id = monitoring.device_response(current, ip='192.0.2.10', device_id='8', now=later)

    assert by_ip == by_mapped
    assert by_ip['found'] == 1 and by_ip['name'] == 'edge-01'
    assert by_ip['last_success_age'] == 2 * 3600 + 600  # worked out at answer time
    assert by_ip['published_at'] == NOW.isoformat() and by_ip['published_age'] == 600
    assert by_v6['name'] == 'core-01' and by_v6['last_success_age'] == 0
    assert by_id['name'] == 'core-01'  # id wins


def test_an_unknown_device_is_not_found(redis):
    current = snapshot(redis)

    for kwargs in ({'ip': '192.0.2.99'}, {'device_id': '99'}, {}, {'ip': 'not an address'}):
        assert monitoring.device_response(current, now=NOW, **kwargs) == {
            'found': 0,
            'published_at': NOW.isoformat(),
            'published_age': 0,
        }
