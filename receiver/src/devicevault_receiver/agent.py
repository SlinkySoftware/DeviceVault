"""The receiver's registration agent (see ``devicevault_protocol.agent``).

Runs in its own thread and applies assignments by handing the receiver its
new configuration on the event loop, waiting until listeners have been
(re)started so the next heartbeat reports them.
"""

import asyncio
import importlib.metadata
from typing import Any

from devicevault_protocol.agent import RegistrationAgent
from devicevault_protocol.crypto.exceptions import CryptoError
from devicevault_protocol.logs import get_logger
from devicevault_protocol.push import PROTOCOLS

from . import hostkey
from .config import ReceiverConfig
from .receiver import Receiver

logger = get_logger('devicevault.receiver.agent')

APPLY_TIMEOUT_SECONDS = 30


def _version() -> str:
    try:
        return importlib.metadata.version('devicevault-receiver')
    except importlib.metadata.PackageNotFoundError:
        return '0.0.0'


class ReceiverAgent(RegistrationAgent):
    def __init__(self, *, receiver: Receiver, loop: asyncio.AbstractEventLoop, **kwargs):
        super().__init__(
            capabilities={
                'receiver': {
                    'protocols': list(PROTOCOLS),
                    'host_key_fingerprint': hostkey.fingerprint(receiver.host_key),
                }
            },
            version=_version(),
            **kwargs,
        )
        self.receiver = receiver
        self.loop = loop

    def apply(self, payload: dict[str, Any], approved: bool) -> None:
        config = ReceiverConfig()  # pending, revoked, or unusable: listen for nothing
        if approved:
            try:
                config = ReceiverConfig.from_assignment(payload.get('receiver') or {}, self.identity)
            except (ValueError, TypeError, CryptoError) as exc:
                logger.error('receiver_config_invalid', extra={'error': str(exc)})
        future = asyncio.run_coroutine_threadsafe(self.receiver.apply(config), self.loop)
        future.result(timeout=APPLY_TIMEOUT_SECONDS)

    def report(self) -> dict[str, Any]:
        return {'queues': [], 'receiver': self.receiver.status()}
