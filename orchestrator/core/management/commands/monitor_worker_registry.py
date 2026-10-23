from __future__ import annotations

import json
import os
import signal
import socket
import time
import uuid
from datetime import datetime, timezone

from django.core.management.base import BaseCommand
from django.utils import timezone as django_timezone
from kombu import Connection, Consumer, Exchange, Producer, Queue

from celery_app import BROKER
from core.models import WorkerRegistration
from core.worker_presence_protocol import (
    EVENT_HEARTBEAT,
    EVENT_PONG,
    EVENT_REGISTER,
    WORKER_CONTROL_EXCHANGE,
    WORKER_EVENTS_EXCHANGE,
    WORKER_EVENTS_QUEUE,
    WORKER_EVENTS_ROUTING_KEY,
)


def _read_int_env(name: str, default: int) -> int:
    raw = os.environ.get(name, '')
    if not raw:
        return default
    try:
        value = int(raw)
    except ValueError:
        return default
    return value if value > 0 else default


def _iso_now() -> str:
    return datetime.now(timezone.utc).isoformat()


class Command(BaseCommand):
    help = 'Monitor worker registration/heartbeat events and send periodic RabbitMQ liveliness probes'

    def handle(self, *args, **options):
        ping_interval_sec = _read_int_env('DEVICEVAULT_WORKER_PING_INTERVAL_SEC', 30)
        reconnect_delay_sec = _read_int_env('DEVICEVAULT_WORKER_RECONNECT_DELAY_SEC', 5)

        running = True

        def _signal_handler(signum, frame):
            nonlocal running
            running = False

        signal.signal(signal.SIGINT, _signal_handler)
        signal.signal(signal.SIGTERM, _signal_handler)

        self.stdout.write(
            self.style.SUCCESS(
                f'Worker monitor started (broker={BROKER}, ping_interval={ping_interval_sec}s)'
            )
        )

        while running:
            try:
                event_exchange = Exchange(WORKER_EVENTS_EXCHANGE, type='direct', durable=True)
                control_exchange = Exchange(WORKER_CONTROL_EXCHANGE, type='fanout', durable=True)
                event_queue = Queue(
                    name=WORKER_EVENTS_QUEUE,
                    exchange=event_exchange,
                    routing_key=WORKER_EVENTS_ROUTING_KEY,
                    durable=True,
                )

                with Connection(BROKER, heartbeat=30) as connection:
                    with connection.channel() as channel:
                        producer = Producer(channel)
                        event_queue.maybe_bind(connection)
                        event_queue.declare()

                        next_ping_at = 0.0

                        def _publish_ping() -> None:
                            probe_id = uuid.uuid4().hex
                            producer.publish(
                                {
                                    'event_type': 'ping',
                                    'probe_id': probe_id,
                                    'requested_at': _iso_now(),
                                },
                                exchange=control_exchange,
                                routing_key='',
                                serializer='json',
                                declare=[control_exchange],
                                retry=True,
                                retry_policy={
                                    'max_retries': 3,
                                    'interval_start': 0.2,
                                    'interval_step': 0.5,
                                    'interval_max': 2,
                                },
                            )
                            now = django_timezone.now()
                            WorkerRegistration.objects.update(last_ping_at=now, last_probe_id=probe_id)

                        def _on_event(body, message):
                            try:
                                self._apply_worker_event(body)
                            finally:
                                message.ack()

                        consumer = Consumer(channel, queues=[event_queue], callbacks=[_on_event], accept=['json'])
                        consumer.consume()

                        while running:
                            now_monotonic = time.monotonic()
                            if now_monotonic >= next_ping_at:
                                _publish_ping()
                                next_ping_at = now_monotonic + ping_interval_sec

                            try:
                                connection.drain_events(timeout=1)
                            except socket.timeout:
                                continue
            except Exception as exc:
                if not running:
                    break
                self.stderr.write(self.style.ERROR(f'Worker monitor loop failed: {exc}'))
                time.sleep(reconnect_delay_sec)

        self.stdout.write(self.style.SUCCESS('Worker monitor stopped'))

    def _apply_worker_event(self, body):
        if not isinstance(body, dict):
            return

        event_type = body.get('event_type')
        if event_type not in {EVENT_REGISTER, EVENT_HEARTBEAT, EVENT_PONG}:
            return

        worker_id = (body.get('worker_id') or '').strip()
        if not worker_id:
            return

        worker_name = (body.get('worker_name') or worker_id).strip()
        worker_type = (body.get('worker_type') or 'unknown').strip() or 'unknown'
        hostname = (body.get('hostname') or '').strip()
        pid = body.get('pid')
        queues = body.get('queues')
        details = body.get('details')
        probe_id = (body.get('probe_id') or '').strip()

        if not isinstance(queues, list):
            queues = []
        queues = [str(queue) for queue in queues if str(queue).strip()]

        if not isinstance(details, dict):
            details = {}

        if pid is not None:
            try:
                pid = int(pid)
            except (TypeError, ValueError):
                pid = None

        now = django_timezone.now()
        defaults = {
            'worker_name': worker_name,
            'worker_type': worker_type,
            'hostname': hostname,
            'pid': pid,
            'queues': queues,
            'details': details,
            'last_seen_at': now,
        }

        if event_type in {EVENT_REGISTER, EVENT_HEARTBEAT}:
            defaults['last_heartbeat_at'] = now
        if event_type == EVENT_PONG:
            defaults['last_pong_at'] = now
        if probe_id:
            defaults['last_probe_id'] = probe_id

        WorkerRegistration.objects.update_or_create(worker_id=worker_id, defaults=defaults)
