"""Events sent to the orchestrator, signed with the receiver's key.

Push events (``devicevault_protocol.push``) and monitoring relay events
(``devicevault_protocol.monitoring``) go to their own orchestrator tasks.
"""

import threading
import time
from collections.abc import Callable
from datetime import UTC, datetime
from typing import Any

from devicevault_protocol import signing
from devicevault_protocol.identity import Identity
from devicevault_protocol.logs import get_logger
from devicevault_protocol.monitoring import EVENT_REFUSED, MONITORING_EVENT_TASK, REFUSAL_WINDOW_SECONDS
from devicevault_protocol.push import EVENT_REJECTED, PUSH_EVENT_TASK
from devicevault_protocol.registration import ORCHESTRATOR_QUEUE

logger = get_logger('devicevault.receiver.events')

# A received event completes a staged backup, so it lives as long as the blob.
EVENT_EXPIRES_SECONDS = 24 * 3600
# At most one rejection report per source, protocol and reason in this window.
REJECTION_WINDOW_SECONDS = 60
# Monitoring events are worth little once old (the orchestrator also refuses them after an hour).
MONITORING_EVENT_EXPIRES_SECONDS = 3600


class Events:
    def __init__(self, identity: Identity, send_task: Callable[..., Any]):
        self.identity = identity
        self._send_task = send_task
        self._lock = threading.Lock()  # sends come from the event loop and the ingest threads
        self._last_rejection: dict[tuple[str, str, str], float] = {}

    def send(self, event: str, **details: Any) -> None:
        self._send(PUSH_EVENT_TASK, EVENT_EXPIRES_SECONDS, event, details)

    def send_monitoring(self, event: str, **details: Any) -> None:
        """A ``monitoring.*`` event (see devicevault_protocol.monitoring)."""
        self._send(MONITORING_EVENT_TASK, MONITORING_EVENT_EXPIRES_SECONDS, event, details)

    def _send(self, task: str, expires: int, event: str, details: dict[str, Any]) -> None:
        payload = {
            'event': event,
            'worker_id': self.identity.worker_id,
            'at': datetime.now(UTC).isoformat(),
            **details,
        }
        envelope = signing.sign(payload, self.identity.signing_key, self.identity.worker_id)
        with self._lock:
            self._send_task(task, args=[envelope], queue=ORCHESTRATOR_QUEUE, expires=expires)

    def monitoring_refused(self, *, source_ip: str, prefix: str, cause: str) -> None:
        """Report a refused relay request, at most once a window per source address."""
        logger.warning('monitoring_refused', extra={'source_ip': source_ip, 'token': prefix, 'cause': cause})
        if not self._first_in_window(('monitoring', source_ip, ''), REFUSAL_WINDOW_SECONDS):
            return
        try:
            self.send_monitoring(EVENT_REFUSED, source_ip=source_ip, prefix=prefix, cause=cause)
        except Exception:  # the broker being down must not break the listener
            logger.exception('monitoring_refusal_not_sent')

    def _first_in_window(self, key: tuple[str, str, str], window: float) -> bool:
        now = time.monotonic()
        with self._lock:
            if now - self._last_rejection.get(key, -window) < window:
                return False
            self._last_rejection[key] = now
            if len(self._last_rejection) > 10_000:  # a scan from many sources; forget the old ones
                cutoff = now - window
                self._last_rejection = {k: t for k, t in self._last_rejection.items() if t >= cutoff}
        return True

    def rejected(self, *, source_ip: str, protocol: str, reason: str, filename: str = '', detail: str = '') -> None:
        """Report a refused push, unless the same one was reported moments ago."""
        logger.warning(
            'push_rejected',
            extra={'source_ip': source_ip, 'protocol': protocol, 'reason': reason, 'file': filename},
        )
        if not self._first_in_window((source_ip, protocol, reason), REJECTION_WINDOW_SECONDS):
            return
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
