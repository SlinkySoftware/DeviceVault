from datetime import UTC, datetime

import pytest

from devicevault_protocol import signing


class Broker:
    """Tasks the orchestrator sent, as (name, args, queue)."""

    def __init__(self):
        self.sent = []

    def __call__(self, name, args=None, queue=None, **kwargs):
        self.sent.append((name, args, queue))


@pytest.fixture
def broker(monkeypatch):
    broker = Broker()
    monkeypatch.setattr('backups.jobs.celery_app.send_task', broker)
    return broker


@pytest.fixture
def setup(db, worker_keys):
    """A backed-up device plus an approved collector and storage worker (as WorkerKeys)."""
    from storage.models import StorageTarget

    from core import workers
    from devices.models import CollectionGroup, Device, DeviceGroup, DeviceType

    group = CollectionGroup.objects.create(name='DMZ', rabbitmq_queue_id='dmz')
    collector = worker_keys('collector-1')
    workers.approve(workers.handle_event(collector.event()), role='collector', collection_groups=[group])
    storage = worker_keys('storage-1')
    target = StorageTarget.objects.create(name='Local', driver='filesystem', config={'path': 'fs'})
    workers.approve(workers.handle_event(storage.event()), role='storage', storage_targets=[target])
    device = Device.objects.create(
        name='Edge 01',
        ip_address='192.0.2.10',
        device_type=DeviceType.objects.create(name='Router'),
        device_group=DeviceGroup.objects.create(name='Core'),
        collection_group=group,
        storage_target=target,
        backup_method='noop',
    )
    return {'device': device, 'group': group, 'collector': collector, 'storage': storage, 'target': target}


def job_event(keys, job, event, **details):
    payload = {
        'job_id': str(job.id),
        'event': event,
        'worker_id': keys.id,
        'at': datetime.now(UTC).isoformat(),
        **details,
    }
    return signing.sign(payload, keys.key, keys.id)
