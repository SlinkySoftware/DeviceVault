import subprocess
import sys

from devicevault_worker.plugins import get_plugin, list_plugins
from devicevault_worker.storage import fs


def test_worker_imports_without_django():
    # Fresh interpreter with Django made unimportable, as in the worker image.
    # (Third-party libraries such as kombu probe for Django opportunistically.)
    code = (
        "import sys; sys.modules['django'] = None; "
        'import devicevault_worker.app, devicevault_worker.collect, '
        'devicevault_worker.storage.tasks, devicevault_worker.presence'
    )
    result = subprocess.run([sys.executable, '-c', code], capture_output=True, text=True, check=False)

    assert result.returncode == 0, result.stderr


def test_worker_app_registers_tasks():
    from devicevault_worker.app import app

    app.loader.import_default_modules()

    assert {'device.collect', 'storage.store', 'storage.read'} <= set(app.tasks)


def test_bundled_plugins_are_discovered():
    keys = {plugin.key for plugin in list_plugins()}

    assert {'noop', 'binary_dummy', 'mikrotik_ssh_export'} <= keys
    assert get_plugin('binary_dummy').is_binary


def test_filesystem_store_and_read_roundtrip(tmp_path):
    config = {'path': str(tmp_path)}

    ref = fs.store_backup('hostname edge-01\n', '1/backup.txt', config)

    assert fs.read_backup(ref, config) == 'hostname edge-01\n'


def test_filesystem_compressed_roundtrip(tmp_path):
    config = {'path': str(tmp_path), 'compress': True}

    ref = fs.store_backup('interface ge-0/0/0\n', '1/backup.txt', config)

    assert fs.read_backup(ref, config) == 'interface ge-0/0/0\n'
