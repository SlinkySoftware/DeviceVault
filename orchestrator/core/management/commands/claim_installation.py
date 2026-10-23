"""Claim the message bus for this database (run by ``migrate``); see core.installation."""

from django.core.management.base import BaseCommand, CommandError

from core.installation import InstallationMismatch, claim


class Command(BaseCommand):
    help = 'Refuse to run against a message bus that another orchestrator database already uses'

    def add_arguments(self, parser):
        parser.add_argument(
            '--force', action='store_true', help='Take the bus over, when this database replaces the old one'
        )

    def handle(self, *args, force=False, **options):
        try:
            installation = claim(force=force)
        except InstallationMismatch as exc:
            raise CommandError(str(exc)) from exc
        self.stdout.write(f'Orchestrator database {installation}')
