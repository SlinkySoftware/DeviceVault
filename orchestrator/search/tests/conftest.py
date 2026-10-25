from datetime import timedelta

import pytest
from django.utils import timezone

from backups.models import BackupJob

NOW = timezone.now()

CISCO_SECRETS = [
    {'pattern': r'^snmp-server community (\S+)', 'encoding': None},
    {'pattern': r'^username \S+ .*?(?:secret|password) 7 (\S+)', 'encoding': 'cisco7'},
    {'pattern': r'^username \S+ .*?(?:secret|password) (?:\d+ )?(\S+)', 'encoding': None},
]

CONFIG = b"""Building configuration...
!
hostname edge-01
snmp-server community public RO
snmp-server location rack-4
username ops password 7 0822455D0A16
interface GigabitEthernet0/1
 ip address 10.12.4.1 255.255.255.0
 ip helper-address 10.0.0.5
end
"""


@pytest.fixture
def catalogue(monkeypatch):
    """The collector driver catalogue the search sees (editable by the test)."""
    drivers = {'cisco_ios': {'volatile_lines': [], 'secret_lines': list(CISCO_SECRETS)}, 'noop': {}}
    for module in ('search.indexing', 'search.query', 'backups.changes'):
        monkeypatch.setattr(f'{module}.driver_catalogue', lambda: drivers)
    return drivers


@pytest.fixture
def contents(monkeypatch):
    """Backup contents by job id; reads are counted in ``contents.reads``."""

    class Contents(dict):
        reads: list

    stored = Contents()
    stored.reads = []

    def read(job):
        stored.reads.append(job.pk)
        if job.pk not in stored:
            raise AssertionError(f'read {job.pk}, which the test did not expect')
        value = stored[job.pk]
        if isinstance(value, Exception):
            raise value
        return value

    monkeypatch.setattr('backups.changes.read_content', read)
    monkeypatch.setattr('search.indexing.read_content', read)
    return stored


@pytest.fixture
def search_on(settings):
    settings.DEVICEVAULT_CONFIG_SEARCH = True


@pytest.fixture
def estate(db, catalogue, contents):
    """Make devices and their stored backups."""
    from devices.models import DeviceGroup, DeviceType
    from storage.models import StorageTarget

    target = StorageTarget.objects.create(name='Local', driver='filesystem', config={'path': 'fs'})
    device_type = DeviceType.objects.create(name='Router')
    groups = {}

    def group(name):
        if name not in groups:
            groups[name] = DeviceGroup.objects.create(name=name)
        return groups[name]

    def device(name, *, group_name='Core', driver='cisco_ios', ip=None):
        from devices.models import Device

        return Device.objects.create(
            name=name,
            ip_address=ip or f'192.0.2.{Device.objects.count() + 10}',
            device_type=device_type,
            device_group=group(group_name) if group_name else None,
            storage_target=target,
            backup_method=driver,
        )

    def backup(device, content=CONFIG, *, hours=0, encrypted=True, sha='a' * 64, **fields):
        job = BackupJob.objects.create(
            device=device,
            state=BackupJob.STORED,
            driver=device.backup_method,
            storage_target=target,
            storage_driver='filesystem',
            storage_ref=f'ref-{device.pk}-{hours}',
            stored_sha256=sha,
            size_bytes=len(content) if isinstance(content, bytes) else 10,
            encrypted=encrypted,
            **fields,
        )
        BackupJob.objects.filter(pk=job.pk).update(created_at=NOW - timedelta(hours=hours))
        job.refresh_from_db()
        contents[job.pk] = content
        return job

    return {'device': device, 'backup': backup, 'group': group, 'target': target}
