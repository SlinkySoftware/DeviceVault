"""Registration agent: announces a worker or receiver and applies its assignment.

Runs as a thread. It:

1. sends a signed ``register`` event to the orchestrator, repeating until an
   assignment arrives, then a ``heartbeat`` every interval reporting the
   assignment version in effect;
2. listens on the control queue for signed assignments, verifies them, pins
   the orchestrator key on the first approved one (trust on first use), and
   hands each accepted assignment to ``apply``.

Subclasses decide what an assignment means: a worker adds and cancels Celery
queue consumers, a receiver opens and closes its listeners. Nothing is
cached: after a restart nothing is applied until the orchestrator sends the
assignment again.
"""

import os
import socket
import threading
import time
from typing import Any

from kombu import Connection, Consumer, Queue

from devicevault_protocol import signing
from devicevault_protocol.env import env_int
from devicevault_protocol.identity import Identity
from devicevault_protocol.logs import get_logger
from devicevault_protocol.registration import (
    ASSIGNMENT,
    ASSIGNMENT_MAX_AGE,
    EVENT_EXPIRES_SECONDS,
    EVENT_HEARTBEAT,
    EVENT_REGISTER,
    ORCHESTRATOR_QUEUE,
    STATUS_APPROVED,
    WORKER_EVENT_TASK,
    control_queue_name,
)
from devicevault_protocol.tasks import ORCHESTRATOR_SIGNER

logger = get_logger('devicevault.agent')


class AssignmentRejected(Exception):
    """An assignment failed verification and was ignored."""


class RegistrationAgent:
    def __init__(
        self,
        *,
        identity: Identity,
        name: str,
        broker_url: str,
        send_task,
        capabilities: dict[str, Any],
        version: str,
        celery_hostname: str = '',
    ):
        self.identity = identity
        self.name = name
        self.celery_hostname = celery_hostname
        self.broker_url = broker_url
        self._send_task = send_task
        self._capabilities = capabilities
        self._version = version
        self.applied_version = 0
        self.status = ''
        self.heartbeat_interval = env_int('DV_WORKER_HEARTBEAT_INTERVAL_SEC', 30, minimum=1)
        self.reconnect_delay = env_int('DV_WORKER_RECONNECT_DELAY_SEC', 5, minimum=1)
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None

    # --- what subclasses provide ----------------------------------------------

    def apply(self, payload: dict[str, Any], approved: bool) -> None:
        """Bring this process in line with a verified assignment.

        ``approved`` is false for pending and revoked assignments, which must
        leave the process doing nothing.
        """

    def report(self) -> dict[str, Any]:
        """Extra fields for every event, describing what is in effect."""
        return {'queues': []}

    # --- events -----------------------------------------------------------------

    def event_payload(self) -> dict[str, Any]:
        return {
            'event': EVENT_HEARTBEAT if self.applied_version else EVENT_REGISTER,
            'worker_id': self.identity.worker_id,
            'name': self.name,
            'celery_hostname': self.celery_hostname,
            'hostname': socket.gethostname(),
            'pid': os.getpid(),
            'version': self._version,
            'signing_key': self.identity.signing_public_key,
            'encryption_key': self.identity.encryption_public_key,
            'capabilities': self._capabilities,
            'applied_version': self.applied_version,
            'orchestrator_key': self.identity.orchestrator_key,
            **self.report(),
        }

    def send_event(self) -> None:
        envelope = signing.sign(self.event_payload(), self.identity.signing_key, self.identity.worker_id)
        self._send_task(WORKER_EVENT_TASK, args=[envelope], queue=ORCHESTRATOR_QUEUE, expires=EVENT_EXPIRES_SECONDS)

    # --- assignments ------------------------------------------------------------

    def handle_assignment(self, envelope: Any) -> bool:
        """Verify and apply an assignment. Returns True if it changed anything."""
        try:
            payload = signing.peek(envelope)
            if payload.get('type') != ASSIGNMENT:
                raise AssignmentRejected('not an assignment')
            if envelope.get('signer') != ORCHESTRATOR_SIGNER:
                raise AssignmentRejected('not signed as the orchestrator')
            offered = payload.get('orchestrator_key')
            pinned = self.identity.orchestrator_key
            if not isinstance(offered, str) or not offered:
                raise AssignmentRejected('no orchestrator key')
            if pinned and offered != pinned:
                raise AssignmentRejected(
                    f'orchestrator key {signing.fingerprint(offered)} does not match the pinned key '
                    f"{signing.fingerprint(pinned)}; reset this worker's state to trust a new orchestrator"
                )
            payload = signing.verify(envelope, signing.public_key_from_b64(offered), max_age=ASSIGNMENT_MAX_AGE)
            if payload.get('worker_id') != self.identity.worker_id:
                raise AssignmentRejected('addressed to another worker')
            if not pinned and payload.get('status') != STATUS_APPROVED:
                raise AssignmentRejected('the first assignment must be an approval')
            version = int(payload['version'])
        except (AssignmentRejected, signing.SignatureError, KeyError, TypeError, ValueError) as exc:
            logger.error('assignment_rejected', extra={'reason': str(exc)})
            return False

        if version < self.applied_version:
            logger.info('assignment_stale', extra={'version': version, 'applied_version': self.applied_version})
            return False
        if not pinned:
            self.identity.pin_orchestrator(offered)
            logger.warning('orchestrator_pinned', extra={'orchestrator_fingerprint': signing.fingerprint(offered)})

        status = payload.get('status', '')
        self.apply(payload, status == STATUS_APPROVED)
        changed = version != self.applied_version or status != self.status
        self.applied_version = version
        self.status = status
        logger.info(
            'assignment_applied',
            extra={'version': version, 'status': status, 'role': payload.get('role'), **self.report()},
        )
        return changed

    # --- lifecycle --------------------------------------------------------------

    def log_identity(self) -> None:
        logger.warning(
            'worker_identity',
            extra={
                'worker_id': self.identity.worker_id,
                'fingerprint': self.identity.fingerprint,
                'orchestrator_pinned': bool(self.identity.orchestrator_key),
            },
        )

    def start(self) -> None:
        self._thread = threading.Thread(target=self._run, name='devicevault-registration', daemon=True)
        self._thread.start()

    def stop(self, timeout: float = 5.0) -> None:
        self._stop.set()
        if self._thread:
            self._thread.join(timeout=timeout)

    def _on_message(self, body: Any, message: Any) -> None:
        try:
            if self.handle_assignment(body):
                self.send_event()  # report the new version straight away
        finally:
            message.ack()

    def _run(self) -> None:
        queue = Queue(control_queue_name(self.identity.worker_id), durable=False, auto_delete=True)
        while not self._stop.is_set():
            try:
                with Connection(self.broker_url, heartbeat=30) as connection:
                    with Consumer(connection, queues=[queue], callbacks=[self._on_message], accept=['json']):
                        next_event = 0.0
                        while not self._stop.is_set():
                            if time.monotonic() >= next_event:
                                self.send_event()
                                next_event = time.monotonic() + self.heartbeat_interval
                            try:
                                connection.drain_events(timeout=1)
                            except TimeoutError:
                                pass
                            # Without this the broker drops the connection after two missed heartbeats.
                            connection.heartbeat_check()
            except Exception:
                logger.exception('registration_loop_failed')
                self._stop.wait(self.reconnect_delay)
