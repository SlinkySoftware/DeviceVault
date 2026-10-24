import stat
import time

from devicevault_protocol import identity as identity_store
from devicevault_protocol import signing

ORCHESTRATOR_KEY = signing.public_key_to_b64(signing.generate_signing_key())


def test_identity_is_created_once_and_persisted_privately(tmp_path):
    path = tmp_path / 'identity.json'
    first = identity_store.load_or_create(path)
    again = identity_store.load_or_create(path)

    assert again.worker_id == first.worker_id
    assert again.fingerprint == first.fingerprint
    assert stat.S_IMODE(path.stat().st_mode) == 0o600


def test_pinned_key_is_visible_to_other_processes(monkeypatch, tmp_path):
    monkeypatch.setenv('DV_STATE_DIR', str(tmp_path))
    identity = identity_store.load_or_create()
    assert identity_store.pinned_orchestrator_key() is None

    time.sleep(0.01)  # distinct mtime
    identity.pin_orchestrator(ORCHESTRATOR_KEY)

    assert signing.public_key_to_b64(identity_store.pinned_orchestrator_key()) == ORCHESTRATOR_KEY
