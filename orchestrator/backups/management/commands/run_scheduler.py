"""Run the scheduler loop (one per orchestrator node; only the leader acts)."""

import signal
import socket
import threading

from django.conf import settings
from django.core.management.base import BaseCommand
from redis import Redis

from backups.scheduler import LEASE_SECONDS, Leadership, tick


class Command(BaseCommand):
    help = 'Run due backup schedules and expire stuck jobs while holding the scheduler lease'

    def handle(self, *args, **options):
        stop = threading.Event()
        for sig in (signal.SIGINT, signal.SIGTERM):
            signal.signal(sig, lambda *_: stop.set())

        interval = settings.DEVICEVAULT_SCHEDULER_INTERVAL_SEC
        # Renewed every tick, so the lease must outlast at least one missed tick.
        leadership = Leadership(
            Redis.from_url(settings.DEVICEVAULT_BUS.redis_url),
            node=socket.gethostname(),
            lease_seconds=max(LEASE_SECONDS, 2 * interval),
        )
        leading = False
        self.stdout.write(f'Scheduler started on {leadership.token} (interval {interval}s)')
        while not stop.is_set():
            try:
                now_leading = leadership.acquire_or_renew()
                if now_leading != leading:
                    self.stdout.write(
                        'This node is now the scheduler leader' if now_leading else 'Lost the scheduler lease'
                    )
                    leading = now_leading
                if leading:
                    tick(leading=leadership.acquire_or_renew)
            except Exception as exc:  # keep running through broker/database hiccups
                self.stderr.write(f'Scheduler tick failed: {exc}')
            stop.wait(interval)
        leadership.release()
        self.stdout.write('Scheduler stopped')
