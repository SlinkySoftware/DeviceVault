import uuid

import pytest

from devicevault_protocol import signing


@pytest.fixture(autouse=True)
def published(monkeypatch):
    """Control messages that would have been sent to workers, as (worker_id, envelope)."""
    sent = []
    monkeypatch.setattr('core.workers.publish_control', lambda worker_id, envelope: sent.append((worker_id, envelope)))
    return sent


class WorkerKeys:
    """A fake worker: identity plus a helper to sign events."""

    def __init__(self, name='collector-1'):
        self.id = str(uuid.uuid4())
        self.name = name
        self.key = signing.generate_signing_key()

    def event(self, applied_version=0, drivers=('noop', 'binary_dummy'), backends=('fs', 'git'), **overrides):
        payload = {
            'event': 'heartbeat' if applied_version else 'register',
            'worker_id': self.id,
            'name': self.name,
            'celery_hostname': f'{self.name}@host',
            'hostname': 'host',
            'pid': 42,
            'version': '0.1.0',
            'signing_key': signing.public_key_to_b64(self.key),
            'encryption_key': signing.b64encode(b'\x01' * 32),
            'capabilities': {
                'collector_drivers': [
                    {
                        'key': key,
                        'name': key.replace('_', ' ').title(),
                        'description': '',
                        'is_binary': key == 'binary_dummy',
                    }
                    for key in drivers
                ],
                'storage_backends': list(backends),
            },
            'applied_version': applied_version,
            'queues': [],
            'orchestrator_key': None,
            **overrides,
        }
        return signing.sign(payload, self.key, self.id)


@pytest.fixture
def worker_keys():
    return WorkerKeys


@pytest.fixture
def approved_collector(db):
    """Register and approve a collector offering noop and binary_dummy."""
    from core import workers

    def make(name='collector-1', groups=(), drivers=('noop', 'binary_dummy')):
        keys = WorkerKeys(name)
        worker = workers.handle_event(keys.event(drivers=drivers))
        return workers.approve(worker, role='collector', collection_groups=list(groups))

    return make
