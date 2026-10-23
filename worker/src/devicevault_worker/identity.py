"""The worker's persistent identity.

Generated on first start and kept in the state volume (``DV_STATE_DIR``,
default ``/var/lib/devicevault``) as ``identity.json``:

- ``worker_id``: a UUID, stable across restarts;
- an Ed25519 signing key, which signs every event the worker sends;
- an X25519 encryption key, for secrets the orchestrator sends it;
- the orchestrator key, pinned on the first accepted assignment.

This is self-generated state, not configuration. Deleting the file resets the
worker: it registers again under a new id and must be approved again.
"""

import json
import os
import tempfile
import uuid
from dataclasses import dataclass
from pathlib import Path

from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey, Ed25519PublicKey
from cryptography.hazmat.primitives.asymmetric.x25519 import X25519PrivateKey
from cryptography.hazmat.primitives.serialization import Encoding, NoEncryption, PrivateFormat, PublicFormat

from devicevault_protocol import signing
from devicevault_protocol.env import env_str

IDENTITY_FILENAME = 'identity.json'


def state_dir() -> Path:
    return Path(env_str('DV_STATE_DIR', '/var/lib/devicevault'))


def identity_path() -> Path:
    return state_dir() / IDENTITY_FILENAME


@dataclass
class Identity:
    worker_id: str
    signing_key: Ed25519PrivateKey
    encryption_key: X25519PrivateKey
    orchestrator_key: str | None
    path: Path

    @property
    def signing_public_key(self) -> str:
        return signing.public_key_to_b64(self.signing_key)

    @property
    def encryption_public_key(self) -> str:
        raw = self.encryption_key.public_key().public_bytes(Encoding.Raw, PublicFormat.Raw)
        return signing.b64encode(raw)

    @property
    def fingerprint(self) -> str:
        return signing.fingerprint(self.signing_public_key)

    def orchestrator_public_key(self) -> Ed25519PublicKey | None:
        return signing.public_key_from_b64(self.orchestrator_key) if self.orchestrator_key else None

    def pin_orchestrator(self, key_b64: str) -> None:
        self.orchestrator_key = key_b64
        self.save()

    def save(self) -> None:
        raw_encryption = self.encryption_key.private_bytes(Encoding.Raw, PrivateFormat.Raw, NoEncryption())
        document = {
            'worker_id': self.worker_id,
            'signing_key': signing.private_key_to_b64(self.signing_key),
            'encryption_key': signing.b64encode(raw_encryption),
            'orchestrator_key': self.orchestrator_key,
        }
        self.path.parent.mkdir(parents=True, exist_ok=True)
        # Write atomically so a crash can never leave a half-written identity.
        fd, tmp = tempfile.mkstemp(dir=self.path.parent, prefix='.identity-')
        try:
            with os.fdopen(fd, 'w', encoding='utf-8') as handle:
                json.dump(document, handle, indent=2)
            os.chmod(tmp, 0o600)
            os.replace(tmp, self.path)
        except BaseException:
            Path(tmp).unlink(missing_ok=True)
            raise


def load(path: Path | None = None) -> Identity:
    path = path or identity_path()
    document = json.loads(path.read_text(encoding='utf-8'))
    return Identity(
        worker_id=str(uuid.UUID(document['worker_id'])),
        signing_key=signing.private_key_from_b64(document['signing_key']),
        encryption_key=X25519PrivateKey.from_private_bytes(signing.b64decode(document['encryption_key'])),
        orchestrator_key=document.get('orchestrator_key'),
        path=path,
    )


def load_or_create(path: Path | None = None) -> Identity:
    path = path or identity_path()
    if path.exists():
        return load(path)
    identity = Identity(
        worker_id=str(uuid.uuid4()),
        signing_key=Ed25519PrivateKey.generate(),
        encryption_key=X25519PrivateKey.generate(),
        orchestrator_key=None,
        path=path,
    )
    identity.save()
    return identity


_cached_key: tuple[float, Ed25519PublicKey | None] | None = None


def pinned_orchestrator_key() -> Ed25519PublicKey | None:
    """The pinned orchestrator key, re-read whenever the identity file changes.

    Task processes call this, because the registration agent in the main worker
    process pins the key after they have started.
    """
    global _cached_key
    path = identity_path()
    try:
        mtime = path.stat().st_mtime
    except FileNotFoundError:
        return None
    if _cached_key is None or _cached_key[0] != mtime:
        _cached_key = (mtime, load(path).orchestrator_public_key())
    return _cached_key[1]
