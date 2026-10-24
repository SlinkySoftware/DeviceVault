import os
import tempfile

# The receiver creates its identity at import time; keep it out of the real
# state directory. Must run before any devicevault_receiver module is imported.
os.environ['DV_STATE_DIR'] = tempfile.mkdtemp(prefix='dv-receiver-tests-')
# The SSH client looks up a local user name; test containers run as a UID with none.
os.environ.setdefault('LOGNAME', 'dv-tests')

import fakeredis  # noqa: E402
import pytest  # noqa: E402

from devicevault_protocol import signing  # noqa: E402


class Sent:
    """Tasks the receiver sent, verified: ``events()`` returns the signed push event payloads."""

    def __init__(self):
        self.tasks = []

    def __call__(self, name, args=None, queue=None, **kwargs):
        self.tasks.append((name, args, queue, kwargs))

    def events(self):
        from devicevault_receiver.app import identity

        public = signing.public_key_from_b64(identity.signing_public_key)
        return [signing.verify(args[0], public) for _, args, _, _ in self.tasks]


@pytest.fixture
def sent():
    return Sent()


@pytest.fixture
def events(sent):
    from devicevault_receiver.app import identity
    from devicevault_receiver.events import Events

    return Events(identity, sent)


@pytest.fixture
def redis():
    return fakeredis.FakeRedis()


@pytest.fixture
def spool(tmp_path):
    path = tmp_path / 'spool'
    path.mkdir()
    return path
