"""Approve registered workers from the command line (automation and development)."""

from django.core.management.base import BaseCommand, CommandError

from core import workers
from core.models import Worker
from devices.models import CollectionGroup
from devicevault_protocol.registration import ROLE_COLLECTOR, ROLES, STATUS_PENDING


class Command(BaseCommand):
    help = 'Approve pending workers whose name matches, with a role and assignment'

    def add_arguments(self, parser):
        parser.add_argument('name', help='Worker name, or a prefix ending in * (e.g. "collector-*")')
        parser.add_argument('--role', required=True, choices=ROLES)
        parser.add_argument('--groups', nargs='*', default=[], help='Collection group queue IDs (collectors)')
        parser.add_argument('--all-groups', action='store_true', help='Assign every collection group')
        parser.add_argument('--backends', nargs='*', default=[], help='Storage backends (storage workers)')

    def handle(self, *args, name, role, groups, all_groups, backends, **options):
        pending = Worker.objects.filter(status=STATUS_PENDING)
        matches = pending.filter(name__startswith=name[:-1]) if name.endswith('*') else pending.filter(name=name)
        if not matches.exists():
            self.stdout.write(f'No pending worker matches "{name}"')
            return

        collection_groups = []
        if role == ROLE_COLLECTOR:
            collection_groups = list(
                CollectionGroup.objects.all()
                if all_groups
                else CollectionGroup.objects.filter(rabbitmq_queue_id__in=groups)
            )
            missing = set(groups) - {g.rabbitmq_queue_id for g in collection_groups}
            if missing:
                raise CommandError(f'Unknown collection group queue IDs: {", ".join(sorted(missing))}')

        for worker in matches:
            workers.approve(worker, role=role, collection_groups=collection_groups, storage_backends=backends)
            self.stdout.write(self.style.SUCCESS(f'Approved {worker.name} ({worker.fingerprint}) as {role}'))
