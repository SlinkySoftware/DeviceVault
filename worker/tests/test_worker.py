import gzip
import subprocess
import sys

import pytest

from devicevault_worker.drivers import get_driver, list_drivers
from devicevault_worker.storage.backends import BACKENDS, BackupName, StorageError


def test_worker_imports_without_django():
    # Fresh interpreter with Django made unimportable, as in the worker image.
    # (Third-party libraries such as kombu probe for Django opportunistically.)
    code = (
        "import sys; sys.modules['django'] = None; "
        'import devicevault_worker.app, devicevault_worker.collect, '
        'devicevault_worker.storage.tasks, devicevault_worker.agent'
    )
    result = subprocess.run([sys.executable, '-c', code], capture_output=True, text=True, check=False)

    assert result.returncode == 0, result.stderr


def test_worker_app_registers_tasks():
    from devicevault_worker.app import app

    app.loader.import_default_modules()

    assert {'job.collect', 'job.store', 'storage.read'} <= set(app.tasks)


def test_bundled_drivers_are_discovered_and_describe_their_params():
    described = {driver.key: driver.describe() for driver in list_drivers()}

    assert {'noop', 'demo_config', 'binary_dummy', 'mikrotik_ssh_export', 'cisco_ios'} <= set(described)
    assert get_driver('binary_dummy').is_binary
    assert 'port' in described['mikrotik_ssh_export']['params_schema']['properties']


NAME = BackupName(device_key='7-edge', job_id='j1', timestamp='20261023T000000Z', extension='.cfg')


@pytest.mark.parametrize('compress', [False, True])
def test_filesystem_backend_roundtrip(tmp_path, compress):
    config = {'path': str(tmp_path), 'compress': compress}
    data = b'hostname edge-01\n\x00\xff'

    ref = BACKENDS['fs'].store(data, NAME, config)

    assert BACKENDS['fs'].read(ref, config) == data
    if compress:
        assert gzip.decompress((tmp_path / ref).read_bytes()) == data


def test_git_backend_keeps_history_per_device(tmp_path):
    config = {'path': str(tmp_path)}
    first = BACKENDS['git'].store(b'v1\n', NAME, config)
    second = BACKENDS['git'].store(b'v2\n', NAME, config)

    assert first != second
    assert BACKENDS['git'].read(first, config) == b'v1\n'
    assert BACKENDS['git'].read(second, config) == b'v2\n'


@pytest.mark.parametrize('backend', ['fs', 'git'])
def test_backends_refuse_paths_outside_their_base(tmp_path, backend):
    config = {'path': str(tmp_path / 'base')}
    escaping = '../outside.cfg' if backend == 'fs' else 'main:../outside.cfg@0000'

    with pytest.raises(StorageError):
        BACKENDS[backend].read(escaping, config)
    with pytest.raises(StorageError):
        BACKENDS[backend].store(b'x', BackupName('../evil', 'j', 't', '.cfg'), config)
