"""Push events sent to the orchestrator, signed with the receiver's key (see devicevault_protocol.push)."""

import threading
import time
from collections.abc import Callable
from datetime import UTC, datetime
from typing import Any

from devicevault_protocol import signing
from devicevault_protocol.identity import Identity
from devicevault_protocol.logs import get_logger
from devicevault_protocol.push import EVENT_REJECTED, PUSH_EVENT_TASK
from devicevault_protocol.registration import ORCHESTRATOR_QUEUE

logger = get_logger('devicevault.receiver.events')

# A received event completes a staged backup, so it lives as long as the blob.
EVENT_EXPIRES_SECONDS = 24 * 3600
# At most one rejection report per source, protocol and reason in this window.
REJECTION_WINDOW_SECONDS = 60


class Events:
    def __init__(self, identity: Identity, send_task: Callable[..., Any]):
        self.identity = identity
        self._send_task = send_task
        self._lock = threading.Lock()  # sends come from the event loop and the ingest threads
        self._last_rejection: dict[tuple[str, str, str], float] = {}

    def send(self, event: str, **details: Any) -> None:
        payload = {
            'event': event,
            'worker_id': self.identity.worker_id,
            'at': datetime.now(UTC).isoformat(),
            **details,
        }
        envelope = signing.sign(payload, self.identity.signing_key, self.identity.worker_id)
        with self._lock:
            self._send_task(PUSH_EVENT_TASK, args=[envelope], queue=ORCHESTRATOR_QUEUE, expires=EVENT_EXPIRES_SECONDS)

    def rejected(self, *, source_ip: str, protocol: str, reason: str, filename: str = '', detail: str = '') -> None:
        """Report a refused push, unless the same one was reported moments ago."""
        logger.warning(
            'push_rejected',
            extra={'source_ip': source_ip, 'protocol': protocol, 'reason': reason, 'file': filename},
        )
        key = (source_ip, protocol, reason)
        now = time.monotonic()
        with self._lock:
            if now - self._last_rejection.get(key, -REJECTION_WINDOW_SECONDS) < REJECTION_WINDOW_SECONDS:
                return
            self._last_rejection[key] = now
            if len(self._last_rejection) > 10_000:  # a scan from many sources; forget the old ones
                cutoff = now - REJECTION_WINDOW_SECONDS
                self._last_rejection = {k: t for k, t in self._last_rejection.items() if t >= cutoff}
        try:
            self.send(
                EVENT_REJECTED,
                source_ip=source_ip,
                protocol=protocol,
                reason=reason,
                filename=filename[:255],
                detail=detail[:255],
            )
        except Exception:  # the broker being down must not break the listener
            logger.exception('push_rejection_not_sent')
