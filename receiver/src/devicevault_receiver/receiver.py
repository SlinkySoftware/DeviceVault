"""The receiver: its current configuration and listeners, running on one asyncio event loop."""

import asyncio
import functools
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from typing import Any

import asyncssh

from devicevault_protocol.logs import get_logger

from . import hostkey
from .config import ReceiverConfig
from .events import Events
from .ingest import Ingestor
from .ssh import SshListener

logger = get_logger('devicevault.receiver')

# Uploads staged at once; more wait their turn (their clients wait for the close to finish).
INGEST_THREADS = 4


class Receiver:
    def __init__(self, *, ingestor: Ingestor, events: Events, host_key: asyncssh.SSHKey, spool_dir: Path):
        self.ingestor = ingestor
        self.events = events
        self.host_key = host_key
        self.spool_dir = spool_dir
        self.config = ReceiverConfig()
        self.authorized_keys: asyncssh.SSHAuthorizedKeys | None = None
        self.ssh = SshListener(self)
        self._pool = ThreadPoolExecutor(max_workers=INGEST_THREADS, thread_name_prefix='ingest')

    async def apply(self, config: ReceiverConfig) -> None:
        """Switch to ``config``: new logins and uploads use it at once; listeners restart if their address changed."""
        self.authorized_keys = None
        if config.ssh.authorized_keys.strip():
            try:
                self.authorized_keys = asyncssh.import_authorized_keys(config.ssh.authorized_keys)
            except (ValueError, asyncssh.KeyImportError) as exc:
                logger.error('authorized_keys_invalid', extra={'error': str(exc)})
        self.config = config
        await self.ssh.configure()

    async def ingest(self, **kwargs: Any) -> str:
        loop = asyncio.get_running_loop()
        return await loop.run_in_executor(
            self._pool, functools.partial(self.ingestor.ingest, config=self.config, **kwargs)
        )

    def status(self) -> dict[str, Any]:
        """Reported in every heartbeat (``receiver`` in devicevault_protocol.push)."""
        return {
            'host_key_fingerprint': hostkey.fingerprint(self.host_key),
            'vault_kid': self.config.encryption.kid if self.config.encryption else None,
            'devices': len(self.config.devices),
            'listeners': {'ssh': self.ssh.status()},
        }

    async def close(self) -> None:
        await self.ssh.stop()
        self._pool.shutdown(wait=True, cancel_futures=False)
