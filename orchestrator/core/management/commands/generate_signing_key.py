"""Generate an orchestrator signing key for DV_SIGNING_KEY."""

from django.core.management.base import BaseCommand

from devicevault_protocol import signing


class Command(BaseCommand):
    help = 'Generate a new Ed25519 signing key for DV_SIGNING_KEY'

    def handle(self, *args, **options):
        key = signing.generate_signing_key()
        self.stdout.write(signing.private_key_to_b64(key))
        self.stderr.write(f'Fingerprint: {signing.fingerprint(signing.public_key_to_b64(key))}')
        self.stderr.write(
            'Set this as DV_SIGNING_KEY on every orchestrator node. Workers pin it when first approved, '
            'so changing it later means resetting every worker.'
        )
