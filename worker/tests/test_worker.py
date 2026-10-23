import subprocess
import sys

from devicevault_worker.drivers import get_driver, list_drivers


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

    assert {'job.collect', 'job.store', 'storage.read', 'storage.check'} <= set(app.tasks)


def test_bundled_drivers_are_discovered_and_describe_their_params():
    described = {driver.key: driver.describe() for driver in list_drivers()}

    assert {'noop', 'demo_config', 'binary_dummy', 'mikrotik_ssh_export', 'cisco_ios'} <= set(described)
    assert get_driver('binary_dummy').is_binary
    assert 'port' in described['mikrotik_ssh_export']['params_schema']['properties']
