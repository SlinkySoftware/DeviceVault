import pytest

from devices.models import CollectionGroup, Device, DeviceGroup, DeviceType


@pytest.fixture
def refs(db, approved_collector):
    approved_collector()  # offers the noop backup method
    return {
        'router': DeviceType.objects.create(name='Router'),
        'switch': DeviceType.objects.create(name='Switch'),
        'core': DeviceGroup.objects.create(name='Core'),
        'edge': DeviceGroup.objects.create(name='Edge'),
        'dmz': CollectionGroup.objects.create(name='DMZ', rabbitmq_queue_id='dmz'),
    }


def _payload(refs, **overrides):
    return {
        'name': 'edge-01',
        'ip_address': '192.0.2.10',
        'device_type': refs['router'].id,
        'device_group': refs['core'].id,
        'collection_group': refs['dmz'].id,
        'backup_method': 'noop',
        **overrides,
    }


def test_create_device_persists_relations(refs, admin_client):
    resp = admin_client.post('/api/devices/', _payload(refs), format='json')

    assert resp.status_code == 201, resp.content
    device = Device.objects.get(name='edge-01')
    assert (device.device_type, device.device_group, device.collection_group) == (
        refs['router'],
        refs['core'],
        refs['dmz'],
    )
    # Responses use the detailed (nested) representation.
    assert resp.json()['device_type']['name'] == 'Router'


def test_update_device_changes_relations(refs, admin_client):
    device = Device.objects.create(
        name='edge-01', ip_address='192.0.2.10', device_type=refs['router'], device_group=refs['core']
    )

    resp = admin_client.put(
        f'/api/devices/{device.id}/',
        _payload(refs, device_type=refs['switch'].id, device_group=refs['edge'].id),
        format='json',
    )

    assert resp.status_code == 200, resp.content
    device.refresh_from_db()
    assert (device.device_type, device.device_group) == (refs['switch'], refs['edge'])


def test_create_rejects_unknown_backup_method(refs, admin_client):
    resp = admin_client.post('/api/devices/', _payload(refs, backup_method='nope'), format='json')

    assert resp.status_code == 400
    assert 'backup_method' in resp.json()


def test_view_only_user_cannot_update_device(refs, make_user, client_for):
    user = make_user('viewer', grants={refs['core']: ['view']})
    device = Device.objects.create(
        name='edge-01', ip_address='192.0.2.10', device_type=refs['router'], device_group=refs['core']
    )

    resp = client_for(user).patch(f'/api/devices/{device.id}/', {'name': 'renamed'}, format='json')

    assert resp.status_code == 403
    device.refresh_from_db()
    assert device.name == 'edge-01'


def test_group_admin_creates_devices_only_in_their_group(refs, make_user, client_for):
    client = client_for(make_user('operator', grants={refs['core']: ['admin'], refs['edge']: ['view']}))

    allowed = client.post('/api/devices/', _payload(refs), format='json')
    denied = client.post('/api/devices/', _payload(refs, name='edge-02', device_group=refs['edge'].id), format='json')

    assert allowed.status_code == 201, allowed.content
    assert denied.status_code == 403


def test_user_preferences_round_trip(make_user, client_for):
    client = client_for(make_user('pref'))

    assert client.patch('/api/user/preferences/', {'theme': 'light'}, format='json').status_code == 200
    assert client.get('/api/user/preferences/').json()['theme'] == 'light'


SSH_SCHEMA = {
    'type': 'object',
    'additionalProperties': False,
    'properties': {'port': {'type': 'integer', 'minimum': 1, 'maximum': 65535, 'default': 22}},
}


def ssh_collector(worker_keys, version='1', schema=SSH_SCHEMA):
    from core import workers

    keys = worker_keys(f'ssh-{version}')
    driver = {'key': 'ssh_thing', 'name': 'SSH thing', 'is_binary': False, 'version': version, 'params_schema': schema}
    event = keys.event(capabilities={'collector_drivers': [driver], 'storage_backends': []})
    return workers.approve(workers.handle_event(event), role='collector')


def test_driver_params_are_validated_against_the_driver_schema(refs, worker_keys, admin_client):
    ssh_collector(worker_keys)
    staff = admin_client

    good = staff.post(
        '/api/devices/', _payload(refs, backup_method='ssh_thing', driver_params={'port': 2222}), format='json'
    )
    bad = staff.post(
        '/api/devices/',
        _payload(refs, name='x', backup_method='ssh_thing', driver_params={'port': 0, 'v': 1}),
        format='json',
    )

    assert good.status_code == 201, good.content
    assert good.json()['driver_params'] == {'port': 2222}
    assert bad.status_code == 400
    assert any('port' in error for error in bad.json()['driver_params'])
    assert any("'v' was unexpected" in error for error in bad.json()['driver_params'])


def test_the_newest_driver_version_describes_it(refs, worker_keys):
    from core.workers import driver_catalogue

    ssh_collector(worker_keys, '2', schema={**SSH_SCHEMA, 'title': 'v2'})
    ssh_collector(worker_keys, '10', schema={**SSH_SCHEMA, 'title': 'v10'})

    entry = driver_catalogue()['ssh_thing']

    assert (entry['version'], entry['versions'], entry['params_schema']['title']) == ('10', ['2', '10'], 'v10')
    assert entry['workers'] == 2
