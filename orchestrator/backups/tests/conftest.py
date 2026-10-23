from datetime import UTC, datetime

import pytest

from devicevault_protocol import signing
from policies.models import BackupSchedule


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
    from core import workers
    from devices.models import CollectionGroup, Device, DeviceGroup, DeviceType
    from storage.models import StorageTarget

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


@pytest.fixture
def nightly(setup, settings):
    settings.DEVICEVAULT_DISPLAY_TIMEZONE = 'Australia/Sydney'
    schedule = BackupSchedule.objects.create(name='Nightly', schedule_type='daily', hour=2, minute=0)
    # 01:00 Sydney (AEDT, UTC+11) on 2026-10-23.
    BackupSchedule.objects.filter(pk=schedule.pk).update(created_at=datetime(2026, 10, 22, 14, 0, tzinfo=UTC))
    setup['device'].schedule = schedule
    setup['device'].save()
    schedule.refresh_from_db()
    return schedule


def job_event(keys, job, event, **details):
    payload = {
        'job_id': str(job.id),
        'event': event,
        'worker_id': keys.id,
        'at': datetime.now(UTC).isoformat(),
        **details,
    }
    return signing.sign(payload, keys.key, keys.id)
