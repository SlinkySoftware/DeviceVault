import os
import tempfile

# The worker app creates its identity at import time; keep it out of the real
# state directory. Must run before any devicevault_worker module is imported.
os.environ['DV_STATE_DIR'] = tempfile.mkdtemp(prefix='dv-worker-tests-')

import pytest  # noqa: E402


@pytest.fixture(autouse=True)
def volume(tmp_path, monkeypatch):
    """The storage volume local drivers write to (``/srv/devicevault`` in the image)."""
    from devicevault_worker.storage.drivers import local

    path = tmp_path / 'volume'
    path.mkdir()
    monkeypatch.setattr(local, 'VOLUME', path)
    return path
