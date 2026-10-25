"""Rebuild every config search document (search.indexing), for example after editing secret patterns."""

from django.core.management.base import BaseCommand, CommandError

from search import indexing
from search.models import SearchDocument


class Command(BaseCommand):
    help = "Rebuild every device's config search document from its newest stored backup."

    def handle(self, *args, **options):
        if not indexing.enabled():
            raise CommandError('Config search is off (DV_CONFIG_SEARCH).')
        # Documents stay searchable until their rebuild replaces them.
        SearchDocument.objects.update(patterns_hash='')
        queued = indexing.queue_stale(force=True)
        self.stdout.write(f'Queued {queued} device(s) for indexing.')
