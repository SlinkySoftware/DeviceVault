import hashlib
import io

import fakeredis
import pytest

from devicevault_protocol import blobs


@pytest.fixture
def redis():
    return fakeredis.FakeRedis()


@pytest.mark.parametrize('size', [0, 1, 10, 11, 35])
def test_blobs_roundtrip_in_chunks(redis, size):
    data = bytes(range(256)) * 2
    data = data[:size]

    ref = blobs.put(redis, 'dv:blob:t', io.BytesIO(data), 60, chunk_size=10)
    sink = io.BytesIO()

    assert ref == {'key': 'dv:blob:t', 'sha256': hashlib.sha256(data).hexdigest(), 'size': size}
    assert blobs.fetch(redis, 'dv:blob:t', sink) == {'sha256': ref['sha256'], 'size': size}
    assert sink.getvalue() == data
    assert len([key for key in redis.keys('dv:blob:t:*')]) == max(1, -(-size // 10))
    assert 0 < redis.ttl('dv:blob:t:0') <= 60


def test_bytes_are_accepted_and_returned(redis):
    blobs.put(redis, 'k', b'config', 60)

    assert blobs.get(redis, 'k') == b'config'


def test_missing_or_incomplete_blobs_read_as_none(redis):
    assert blobs.get(redis, 'k') is None

    blobs.put(redis, 'k', b'0123456789abc', 60, chunk_size=5)
    redis.delete('k:1')  # one chunk expired

    assert blobs.get(redis, 'k') is None


def test_delete_removes_every_chunk(redis):
    blobs.put(redis, 'k', b'0123456789abc', 60, chunk_size=5)

    blobs.delete(redis, 'k')

    assert redis.keys('*') == []
