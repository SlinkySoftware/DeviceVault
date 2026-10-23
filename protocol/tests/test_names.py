import uuid

from devicevault_protocol.names import collection_queue_name, storage_target_queue_name


def test_collection_queue_name():
    assert collection_queue_name('dmz') == 'collector.group.dmz'


def test_storage_target_queue_name():
    target = uuid.UUID('6f1c2a7e-0000-4000-8000-000000000001')

    assert storage_target_queue_name(target) == 'storage.target.6f1c2a7e-0000-4000-8000-000000000001'
