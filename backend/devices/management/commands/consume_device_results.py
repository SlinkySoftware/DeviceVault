from __future__ import annotations

import os
import json
import time
import signal
from datetime import datetime

from django.core.management.base import BaseCommand
from redis import Redis

from devices.models import Device, DeviceBackupResult
from celery_app import app as celery_app


class Command(BaseCommand):
    help = 'Consume device backup results from Redis Stream and persist to the DB'

    storage_backend_map = {
        'git': 'git',
        'fs': 'fs',
        'filesystem': 'fs',
    }

    def handle(self, *args, **options):
        redis_url = os.environ.get('DEVICEVAULT_REDIS_URL', 'redis://localhost:6379/1')
        stream = os.environ.get('DEVICEVAULT_RESULTS_STREAM', 'device:results')
        group = os.environ.get('DEVICEVAULT_RESULTS_GROUP', 'devicevault')
        consumer = os.environ.get('DEVICEVAULT_RESULTS_CONSUMER', f'consumer-{os.getpid()}')

        r = Redis.from_url(redis_url)

        # Ensure consumer group exists
        try:
            r.xgroup_create(stream, group, id='0', mkstream=True)
        except Exception as exc:
            # Ignore if group already exists
            if 'BUSYGROUP' not in str(exc):
                raise

        running = True

        def _signal(signum, frame):
            nonlocal running
            running = False

        signal.signal(signal.SIGINT, _signal)
        signal.signal(signal.SIGTERM, _signal)

        self.stdout.write(self.style.SUCCESS(f'Listening for results on stream "{stream}" as group "{group}" consumer "{consumer}"'))

        while running:
            try:
                resp = r.xreadgroup(group, consumer, {stream: '>'}, count=10, block=2000)
                if not resp:
                    continue

                for sname, messages in resp:
                    for msg_id, fields in messages:
                        # decode bytes to str
                        try:
                            data = {k.decode(): v.decode() for k, v in fields.items()}
                        except Exception:
                            data = {k: v for k, v in fields.items()}

                        task_id = data.get('task_id', '')
                        task_identifier = data.get('task_identifier', '')
                        device_id = data.get('device_id') or None
                        status = data.get('status', 'failure')
                        log_text = data.get('log', '[]')
                        device_config = data.get('device_config', '')
                        collection_duration_ms = data.get('collection_duration_ms') or None
                        initiated_at_str = data.get('initiated_at', '')

                        # Idempotency: skip if task_identifier already persisted
                        if task_identifier and DeviceBackupResult.objects.filter(task_identifier=task_identifier).exists():
                            r.xack(stream, group, msg_id)
                            self.stdout.write(f'Skipped idempotent message: {task_identifier}')
                            continue

                        try:
                            device_obj = None
                            if device_id:
                                try:
                                    device_obj = Device.objects.get(pk=int(device_id))
                                except Device.DoesNotExist:
                                    self.stderr.write(self.style.WARNING(f'Device {device_id} not found, skipping message {msg_id}'))
                                    # Still acknowledge the message to prevent reprocessing
                                    r.xack(stream, group, msg_id)
                                    continue
                                except Exception as exc:
                                    self.stderr.write(self.style.ERROR(f'Error looking up device {device_id}: {exc}'))
                                    # Still acknowledge to prevent infinite retries
                                    r.xack(stream, group, msg_id)
                                    continue

                            if not device_obj:
                                self.stderr.write(self.style.WARNING(f'No device specified in message {msg_id}, skipping'))
                                # Still acknowledge
                                r.xack(stream, group, msg_id)
                                continue

                            # Parse initiated_at timestamp
                            initiated_at = None
                            if initiated_at_str:
                                try:
                                    from django.utils.dateparse import parse_datetime
                                    initiated_at = parse_datetime(initiated_at_str)
                                except Exception:
                                    pass
                            
                            # Convert collection_duration_ms to int if present
                            collection_duration_int = None
                            if collection_duration_ms:
                                try:
                                    collection_duration_int = int(collection_duration_ms)
                                except (ValueError, TypeError):
                                    pass
                            
                            # Calculate overall duration (step 1 to step 5)
                            overall_duration_int = None
                            if initiated_at and collection_duration_int is not None:
                                try:
                                    now_timestamp_ms = int(datetime.utcnow().timestamp() * 1000)
                                    initiated_timestamp_ms = int(initiated_at.timestamp() * 1000)
                                    overall_duration_int = now_timestamp_ms - initiated_timestamp_ms
                                except Exception:
                                    pass

                            DeviceBackupResult.objects.create(
                                task_id=task_id or '',
                                task_identifier=task_identifier,
                                device=device_obj,
                                status=status,
                                timestamp=datetime.utcnow(),
                                log=log_text,
                                initiated_at=initiated_at,
                                collection_duration_ms=collection_duration_int,
                                overall_duration_ms=overall_duration_int
                            )

                            if status == 'success':
                                self._enqueue_storage_task(
                                    device_obj,
                                    task_id=task_id,
                                    task_identifier=task_identifier,
                                    device_config=device_config,
                                )

                            r.xack(stream, group, msg_id)
                            self.stdout.write(self.style.SUCCESS(f'Persisted result for device {device_id}: {task_identifier}'))
                        except Exception as exc:
                            self.stderr.write(self.style.ERROR(f'Failed to persist message {msg_id}: {exc}'))
                            # Still acknowledge to prevent getting stuck on bad messages
                            r.xack(stream, group, msg_id)
            except Exception as exc:
                self.stderr.write(f'Error reading stream: {exc}')
                time.sleep(1)

    def _enqueue_storage_task(self, device_obj, *, task_id: str, task_identifier: str, device_config: str) -> None:
        """Schedule storage via Celery worker, routed by storage backend."""
        location = device_obj.backup_location
        if not location:
            self.stderr.write(self.style.WARNING(f'No backup location configured for device {device_obj.pk}, skipping storage dispatch'))
            return

        backend_key = self.storage_backend_map.get((location.location_type or '').lower())
        if not backend_key:
            self.stderr.write(self.style.WARNING(f'Unsupported storage backend "{location.location_type}" for device {device_obj.pk}, skipping storage dispatch'))
            return

        payload = {
            'task_id': task_id or '',
            'task_identifier': task_identifier,
            'device_id': device_obj.pk,
            'storage_backend': backend_key,
            'storage_config': location.config or {},
            'device_config': device_config or '',
        }

        queue = f'storage.{backend_key}'

        try:
            celery_app.send_task(
                'storage.store',
                args=[payload],
                queue=queue,
                routing_key=queue,
            )
            self.stdout.write(self.style.SUCCESS(f'Storage task queued on {queue} for device {device_obj.pk} ({task_identifier})'))
        except Exception as exc:
            self.stderr.write(self.style.ERROR(f'Failed to enqueue storage task for device {device_obj.pk}: {exc}'))
