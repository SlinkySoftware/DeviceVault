"""Queue change summaries for stored backups that have none (backups.changes)."""

from django.core.management.base import BaseCommand

from backups.changes import request_summary
from backups.models import BackupJob


class Command(BaseCommand):
    help = 'Queue change summaries for stored backups without one (such as those stored before summaries existed)'

    def add_arguments(self, parser):
        parser.add_argument('--device', type=int, help='Only this device (id)')
        parser.add_argument('--redo', action='store_true', help='Also redo backups that already have a summary')

    def handle(self, *args, device=None, redo=False, **options):
        jobs = BackupJob.objects.filter(state=BackupJob.STORED, prune_requested_at__isnull=True, pruned_at__isnull=True)
        if device is not None:
            jobs = jobs.filter(device_id=device)
        if not redo:
            jobs = jobs.filter(changed__isnull=True, summary_error='')
        count = 0
        for job in jobs.order_by('created_at').iterator():
            request_summary(job)
            count += 1
        self.stdout.write(f'Queued {count} change summaries; the events service works through them')
