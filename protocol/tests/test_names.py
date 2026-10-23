import pytest

from devicevault_protocol.names import collection_queue_name, storage_backend_for, storage_queue_name


def test_collection_queue_name():
    assert collection_queue_name('dmz') == 'collector.group.dmz'


@pytest.mark.parametrize(
    ('location_type', 'expected'),
    [('git', 'git'), ('Filesystem', 'fs'), ('fs', 'fs'), ('s3', None), ('', None), (None, None)],
)
def test_storage_backend_for(location_type, expected):
    assert storage_backend_for(location_type) == expected


def test_storage_queue_name():
    assert storage_queue_name('fs') == 'storage.fs'
