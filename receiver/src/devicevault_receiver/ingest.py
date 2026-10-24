"""Turning an accepted upload into a staged backup and a ``received`` event.

Runs in a worker thread (it blocks on Redis and the broker). The upload is
already spooled to disk; it is read once to tell text from binary, then
encrypted to the vault key (when payload encryption is on) into a second
temporary file, and staged in Redis in chunks.
"""

import codecs
import tempfile
import time
import uuid
from collections.abc import Callable
from datetime import UTC, datetime
from pathlib import Path
from typing import BinaryIO

from devicevault_protocol import blobs
from devicevault_protocol.crypto import VaultPublicKey, encrypt_stream
from devicevault_protocol.jobs import BLOB_TTL_SECONDS, blob_key
from devicevault_protocol.logs import get_logger
from devicevault_protocol.push import EVENT_RECEIVED

from .config import Device, ReceiverConfig
from .events import Events

logger = get_logger('devicevault.receiver.ingest')

_READ_SIZE = 1024 * 1024


def is_text(handle: BinaryIO) -> bool:
    """Whether the file is UTF-8 without NUL bytes (configurations are text; images and archives are not)."""
    decoder = codecs.getincrementaldecoder('utf-8')()
    try:
        while chunk := handle.read(_READ_SIZE):
            if b'\x00' in chunk:
                return False
            decoder.decode(chunk)
        decoder.decode(b'', final=True)
    except UnicodeDecodeError:
        return False
    return True


class Ingestor:
    def __init__(self, *, redis, events: Events, spool_dir: Path, now: Callable[[], float] = time.monotonic):
        self.redis = redis
        self.events = events
        self.spool_dir = spool_dir
        self._now = now

    def ingest(
        self, *, config: ReceiverConfig, device: Device, source_ip: str, protocol: str, filename: str, path: Path
    ) -> str:
        """Stage ``path`` as a backup of ``device`` and tell the orchestrator. Returns the job id."""
        started = self._now()
        job_id = str(uuid.uuid4())
        with open(path, 'rb') as upload:
            text = is_text(upload)
            upload.seek(0)
            if config.encryption:
                with tempfile.TemporaryFile(dir=self.spool_dir) as encrypted:
                    vault = VaultPublicKey(config.encryption.kid, config.encryption.public_key)
                    encrypt_stream(upload, encrypted, vault, aad_fields={'job_id': job_id, 'device_id': device.id})
                    encrypted.seek(0)
                    blob = blobs.put(self.redis, blob_key(job_id), encrypted, BLOB_TTL_SECONDS)
            else:
                blob = blobs.put(self.redis, blob_key(job_id), upload, BLOB_TTL_SECONDS)
        size = path.stat().st_size
        message = f'received {filename} ({size} bytes) from {source_ip} over {protocol}'
        self.events.send(
            EVENT_RECEIVED,
            job_id=job_id,
            device_id=device.id,
            source_ip=source_ip,
            protocol=protocol,
            filename=filename,
            blob=blob,
            is_binary=not text,
            encrypted=config.encryption is not None,
            duration_ms=int((self._now() - started) * 1000),
            log=[_entry(message)],
        )
        logger.info('push_received', extra={'job_id': job_id, 'device_id': device.id, 'file': filename})
        return job_id


def _entry(message: str) -> dict[str, str]:
    return {'source': 'receiver', 'timestamp': datetime.now(UTC).isoformat(), 'severity': 'INFO', 'message': message}
