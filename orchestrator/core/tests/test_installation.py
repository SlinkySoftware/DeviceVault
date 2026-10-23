import uuid

import fakeredis
import pytest

from core.installation import CLAIM_KEY, InstallationMismatch, claim, installation_id


@pytest.fixture
def redis():
    return fakeredis.FakeRedis()


def test_nodes_sharing_a_database_share_the_bus(db, redis):
    first = claim(redis)
    assert first == installation_id()
    assert claim(redis) == first
    assert redis.get(CLAIM_KEY) == first.encode()


def test_a_second_database_is_refused_until_it_takes_over(db, redis):
    other = str(uuid.uuid4())  # e.g. another node's own SQLite file
    redis.set(CLAIM_KEY, other)
    with pytest.raises(InstallationMismatch, match=other):
        claim(redis)
    assert redis.get(CLAIM_KEY) == other.encode()

    assert claim(redis, force=True) == installation_id()
    assert claim(redis) == installation_id()
