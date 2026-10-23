"""Celery worker self-registration and liveliness response over RabbitMQ."""

import logging
import os
import socket
import threading
import time
from datetime import UTC, datetime
from typing import Any

from celery.signals import worker_ready, worker_shutdown
from kombu import Connection, Consumer, Exchange, Producer, Queue

from devicevault_protocol.env import env_list
from devicevault_protocol.presence import (
    EVENT_HEARTBEAT,
    EVENT_PING,
    EVENT_PONG,
    EVENT_REGISTER,
    WORKER_CONTROL_EXCHANGE,
    WORKER_EVENTS_EXCHANGE,
    WORKER_EVENTS_ROUTING_KEY,
)
from devicevault_worker.app import bus

logger = logging.getLogger('devicevault.worker.presence')

_presence_agent = None
_presence_lock = threading.Lock()


def _iso_now() -> str:
    return datetime.now(UTC).isoformat()


def _read_int_env(name: str, default: int) -> int:
    raw = os.environ.get(name, '')
    if not raw:
        return default
    try:
        value = int(raw)
    except ValueError:
        logger.warning('Invalid integer for %s: %r. Using %s.', name, raw, default)
        return default
    if value <= 0:
        logger.warning('Non-positive value for %s: %r. Using %s.', name, raw, default)
        return default
    return value


def _extract_queue_names(sender: Any) -> list[str]:
    """Return the queues this worker consumes (-Q), not every queue Celery knows about."""
    configured = env_list('DV_WORKER_QUEUES')
    if configured:
        return sorted(set(configured))
    app = getattr(sender, 'app', None)
    consume_from = getattr(getattr(getattr(app, 'amqp', None), 'queues', None), 'consume_from', None)
    return sorted(consume_from or [])


def _infer_worker_type(queues: list[str]) -> str:
    has_storage = any(queue.startswith('storage.') for queue in queues)
    has_collection = any(queue.startswith('collector.group.') or queue == 'default' for queue in queues)
    if has_storage and has_collection:
        return 'mixed'
    if has_storage:
        return 'storage'
    if has_collection:
        return 'collection'
    return 'unknown'


class WorkerPresenceAgent:
    def __init__(
        self, *, broker_url: str, worker_id: str, worker_name: str, hostname: str, pid: int, queues: list[str]
    ):
        self.broker_url = broker_url
        self.worker_id = worker_id
        self.worker_name = worker_name
        self.hostname = hostname
        self.pid = pid
        self.queues = queues
        self.worker_type = _infer_worker_type(queues)

        self.heartbeat_interval_sec = _read_int_env('DV_WORKER_HEARTBEAT_INTERVAL_SEC', 30)
        self.reconnect_delay_sec = _read_int_env('DV_WORKER_RECONNECT_DELAY_SEC', 5)
        self.accepted_message_ttl_sec = _read_int_env('DV_WORKER_CONTROL_MESSAGE_TTL_SEC', 60)

        self._stop_event = threading.Event()
        self._thread = None

    def start(self) -> None:
        if self._thread and self._thread.is_alive():
            return
        self._thread = threading.Thread(target=self._run, name=f'worker-presence-{self.worker_id}', daemon=True)
        self._thread.start()

    def stop(self, timeout: float = 5.0) -> None:
        self._stop_event.set()
        if self._thread:
            self._thread.join(timeout=timeout)

    def _event_payload(self, event_type: str, probe_id: str = '') -> dict[str, Any]:
        payload = {
            'event_type': event_type,
            'worker_id': self.worker_id,
            'worker_name': self.worker_name,
            'worker_type': self.worker_type,
            'hostname': self.hostname,
            'pid': self.pid,
            'queues': self.queues,
            'reported_at': _iso_now(),
        }
        if probe_id:
            payload['probe_id'] = probe_id
        return payload

    def _publish(self, producer: Producer, event_exchange: Exchange, event_type: str, probe_id: str = '') -> None:
        producer.publish(
            self._event_payload(event_type, probe_id=probe_id),
            exchange=event_exchange,
            routing_key=WORKER_EVENTS_ROUTING_KEY,
            serializer='json',
            declare=[event_exchange],
            retry=True,
            retry_policy={'max_retries': 3, 'interval_start': 0.2, 'interval_step': 0.5, 'interval_max': 2},
        )

    def _handle_control_message(self, body: Any, message: Any, producer: Producer, event_exchange: Exchange) -> None:
        try:
            payload = body if isinstance(body, dict) else {}
            if payload.get('event_type') != EVENT_PING:
                return

            target_worker_id = payload.get('worker_id')
            if target_worker_id and target_worker_id != self.worker_id:
                return

            probe_id = payload.get('probe_id', '')
            self._publish(producer, event_exchange, EVENT_PONG, probe_id=probe_id)
        finally:
            message.ack()

    def _run(self) -> None:
        event_exchange = Exchange(WORKER_EVENTS_EXCHANGE, type='direct', durable=True)
        control_exchange = Exchange(WORKER_CONTROL_EXCHANGE, type='fanout', durable=True)
        control_queue_name = f'devicevault.worker.control.{self.worker_id}'

        while not self._stop_event.is_set():
            try:
                with Connection(self.broker_url, heartbeat=30) as connection:
                    with connection.channel() as channel:
                        producer = Producer(channel)
                        control_queue = Queue(
                            name=control_queue_name,
                            exchange=control_exchange,
                            routing_key='',
                            durable=False,
                            auto_delete=True,
                            exclusive=True,
                            queue_arguments={
                                'x-message-ttl': self.accepted_message_ttl_sec * 1000,
                            },
                        )

                        control_queue.maybe_bind(connection)
                        control_queue.declare()

                        self._publish(producer, event_exchange, EVENT_REGISTER)
                        next_heartbeat_at = time.monotonic() + self.heartbeat_interval_sec

                        consumer = Consumer(
                            channel,
                            queues=[control_queue],
                            callbacks=[
                                lambda body, message: self._handle_control_message(
                                    body, message, producer, event_exchange
                                )
                            ],
                            accept=['json'],
                        )
                        consumer.consume()

                        while not self._stop_event.is_set():
                            timeout = max(0.5, min(1.0, next_heartbeat_at - time.monotonic()))
                            try:
                                connection.drain_events(timeout=timeout)
                            except TimeoutError:
                                pass

                            now = time.monotonic()
                            if now >= next_heartbeat_at:
                                self._publish(producer, event_exchange, EVENT_HEARTBEAT)
                                next_heartbeat_at = now + self.heartbeat_interval_sec
            except Exception:
                logger.exception('Worker presence connection loop failed for %s', self.worker_id)
                if not self._stop_event.is_set():
                    time.sleep(self.reconnect_delay_sec)


@worker_ready.connect
def _on_worker_ready(sender=None, **kwargs):
    global _presence_agent

    if sender is None:
        return

    with _presence_lock:
        if _presence_agent is not None:
            return

        worker_name = (
            getattr(sender, 'hostname', '') or getattr(sender, 'name', '') or os.environ.get('HOSTNAME', 'worker')
        )
        queues = _extract_queue_names(sender)
        hostname = os.environ.get('HOSTNAME', socket.gethostname())
        pid = os.getpid()

        _presence_agent = WorkerPresenceAgent(
            broker_url=bus.broker_url,
            worker_id=worker_name,
            worker_name=worker_name,
            hostname=hostname,
            pid=pid,
            queues=queues,
        )
        _presence_agent.start()
        logger.info(
            'Worker presence started: worker=%s type=%s queues=%s',
            worker_name,
            _presence_agent.worker_type,
            ','.join(queues) if queues else '(none)',
        )


@worker_shutdown.connect
def _on_worker_shutdown(sender=None, **kwargs):
    global _presence_agent
    with _presence_lock:
        if _presence_agent is not None:
            _presence_agent.stop()
            _presence_agent = None
