from __future__ import annotations

import os
import json
import time
import signal
from datetime import datetime

from django.core.management.base import BaseCommand
from redis import Redis

from devices.models import Device
from backups.models import StoredBackup


class Command(BaseCommand):
    help = 'Consume storage results from Redis Stream and persist to StoredBackup'

    def handle(self, *args, **options):
        redis_url = os.environ.get('DEVICEVAULT_REDIS_URL', 'redis://localhost:6379/1')
        stream = os.environ.get('DEVICEVAULT_STORAGE_RESULTS_STREAM', 'storage:results')
        group = os.environ.get('DEVICEVAULT_STORAGE_RESULTS_GROUP', 'devicevault-storage')
        consumer = os.environ.get('DEVICEVAULT_STORAGE_RESULTS_CONSUMER', f'storage-consumer-{os.getpid()}')

        r = Redis.from_url(redis_url)

        try:
            r.xgroup_create(stream, group, id='0', mkstream=True)
        except Exception as exc:
            if 'BUSYGROUP' not in str(exc):
                raise

        running = True

        def _signal(signum, frame):
            nonlocal running
            running = False

        signal.signal(signal.SIGINT, _signal)
        signal.signal(signal.SIGTERM, _signal)

        self.stdout.write(self.style.SUCCESS(f'Listening for storage results on stream "{stream}" as group "{group}" consumer "{consumer}"'))

        while running:
            try:
                resp = r.xreadgroup(group, consumer, {stream: '>'}, count=10, block=2000)
                if not resp:
                    continue

                for sname, messages in resp:
                    for msg_id, fields in messages:
                        try:
                            data = {k.decode(): v.decode() for k, v in fields.items()}
                        except Exception:
                            data = {k: v for k, v in fields.items()}

                        task_id = data.get('task_id', '')
                        task_identifier = data.get('task_identifier', '')
                        device_id = data.get('device_id') or None
                        status = data.get('status', 'failure')
                        log_text = data.get('log', '[]')
                        storage_backend = data.get('storage_backend', '')
                        storage_ref = data.get('storage_ref', '')
                        operation = data.get('operation', 'store')
                        storage_duration_ms = data.get('storage_duration_ms') or None

                        if operation and operation != 'store':
                            r.xack(stream, group, msg_id)
                            self.stdout.write(f'Skipped non-store operation: {operation} ({task_identifier})')
                            continue

                        if not device_id:
                            self.stderr.write(self.style.WARNING(f'No device_id in storage message {msg_id}, skipping'))
                            r.xack(stream, group, msg_id)
                            continue

                        # Idempotency: skip if already persisted
                        if task_identifier and StoredBackup.objects.filter(task_identifier=task_identifier).exists():
                            r.xack(stream, group, msg_id)
                            self.stdout.write(f'Skipped idempotent storage message: {task_identifier}')
                            continue

                        try:
                            device_obj = None
                            try:
                                device_obj = Device.objects.get(pk=int(device_id))
                            except Device.DoesNotExist:
                                self.stderr.write(self.style.WARNING(f'Device {device_id} not found for storage message {msg_id}'))
                                r.xack(stream, group, msg_id)
                                continue
                            except Exception as exc:
                                self.stderr.write(self.style.ERROR(f'Error looking up device {device_id}: {exc}'))
                                r.xack(stream, group, msg_id)
                                continue

                            StoredBackup.objects.create(
                                task_id=task_id or '',
                                task_identifier=task_identifier,
                                device=device_obj,
                                storage_backend=storage_backend,
                                storage_ref=storage_ref,
                                status=status,
                                timestamp=datetime.utcnow(),
                                log=log_text,
                                storage_duration_ms=int(storage_duration_ms) if storage_duration_ms and storage_duration_ms != '' else None,
                            )
                            
                            # Update overall duration in DeviceBackupResult (step 1 to step 9)
                            # Find the related DeviceBackupResult and update overall_duration_ms
                            if task_identifier and status == 'success':
                                try:
                                    from devices.models import DeviceBackupResult
                                    backup_result = DeviceBackupResult.objects.filter(task_identifier=task_identifier).first()
                                    if backup_result and backup_result.initiated_at:
                                        now_timestamp_ms = int(datetime.utcnow().timestamp() * 1000)
                                        initiated_timestamp_ms = int(backup_result.initiated_at.timestamp() * 1000)
                                        overall_duration_ms = now_timestamp_ms - initiated_timestamp_ms
                                        backup_result.overall_duration_ms = overall_duration_ms
                                        backup_result.save(update_fields=['overall_duration_ms'])
                                except Exception as exc:
                                    self.stderr.write(self.style.WARNING(f'Failed to update overall duration for {task_identifier}: {exc}'))
                            
                            r.xack(stream, group, msg_id)
                            self.stdout.write(self.style.SUCCESS(f'Persisted storage result for device {device_id}: {task_identifier} -> {storage_backend}'))
                        except Exception as exc:
                            self.stderr.write(self.style.ERROR(f'Failed to persist storage message {msg_id}: {exc}'))
                            r.xack(stream, group, msg_id)
            except Exception as exc:
                self.stderr.write(f'Error reading storage stream: {exc}')
                time.sleep(1)
