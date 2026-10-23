"""Approve registered workers from the command line (automation and development)."""

from django.core.management.base import BaseCommand, CommandError

from core import workers
from core.models import Worker
from devices.models import CollectionGroup
from devicevault_protocol.registration import ROLE_COLLECTOR, ROLE_STORAGE, ROLES, STATUS_PENDING
from storage.models import StorageTarget


class Command(BaseCommand):
    help = 'Approve pending workers whose name matches, with a role and assignment'

    def add_arguments(self, parser):
        parser.add_argument('name', help='Worker name, or a prefix ending in * (e.g. "collector-*")')
        parser.add_argument('--role', required=True, choices=ROLES)
        parser.add_argument('--groups', nargs='*', default=[], help='Collection group queue IDs (collectors)')
        parser.add_argument('--all-groups', action='store_true', help='Assign every collection group')
        parser.add_argument('--targets', nargs='*', default=[], help='Storage target names (storage workers)')
        parser.add_argument(
            '--all-targets', action='store_true', help='Assign every storage target the worker can serve'
        )

    def handle(self, *args, name, role, groups, all_groups, targets, all_targets, **options):
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

        named = list(StorageTarget.objects.filter(name__in=targets))
        missing = set(targets) - {t.name for t in named}
        if missing:
            raise CommandError(f'Unknown storage targets: {", ".join(sorted(missing))}')

        for worker in matches:
            storage_targets = []
            if role == ROLE_STORAGE:
                candidates = StorageTarget.objects.all() if all_targets else named
                storage_targets = [
                    t for t in candidates if not all_targets or not workers.approval_target_problems(worker, [t])
                ]
                problems = workers.approval_target_problems(worker, storage_targets)
                if problems:
                    raise CommandError('; '.join(problems))
            workers.approve(worker, role=role, collection_groups=collection_groups, storage_targets=storage_targets)
            self.stdout.write(self.style.SUCCESS(f'Approved {worker.name} ({worker.fingerprint}) as {role}'))
