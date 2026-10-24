from datetime import UTC, datetime

import pytest

from backups.tests.conftest import broker, setup  # noqa: F401 (fixtures)
from devicevault_protocol import signing

RECEIVER_CAPABILITIES = {'receiver': {'protocols': ['ssh']}}


@pytest.fixture
def receiver(db, worker_keys):
    """An approved receiver, as (WorkerKeys, Worker)."""
    from core import workers

    keys = worker_keys('receiver-1')
    worker = workers.approve(workers.handle_event(keys.event(capabilities=RECEIVER_CAPABILITIES)), role='receiver')
    return keys, worker


def push_event(keys, event, **details):
    payload = {
        'event': event,
        'worker_id': keys.id,
        'at': datetime.now(UTC).isoformat(),
        'protocol': 'ssh',
        **details,
    }
    return signing.sign(payload, keys.key, keys.id)
