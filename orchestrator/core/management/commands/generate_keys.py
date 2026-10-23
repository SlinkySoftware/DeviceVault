"""Generate the orchestrator's keys: DV_SIGNING_KEY, DV_DATA_KEYS and DV_VAULT_KEYS."""

import os
from datetime import UTC, datetime

from django.core.management.base import BaseCommand

from devicevault_protocol import signing
from devicevault_protocol.crypto import ecies
from devicevault_protocol.crypto.constants import AES_KEY_BYTES


class Command(BaseCommand):
    help = 'Print new orchestrator keys as env lines (DV_SIGNING_KEY, DV_DATA_KEYS, DV_VAULT_KEYS)'
    # The key checks would fail for want of the very keys this creates.
    requires_system_checks = []

    def add_arguments(self, parser):
        parser.add_argument(
            '--only', choices=['signing', 'data', 'vault'], help='Print one key (bare value) for rotation'
        )
        parser.add_argument('--kid', help='Key id for data and vault keys (default: date-based)')

    def handle(self, *args, only=None, kid=None, **options):
        kid = kid or datetime.now(UTC).strftime('k%Y%m%d')
        signing_key = signing.generate_signing_key()
        values = {
            'signing': ('DV_SIGNING_KEY', signing.private_key_to_b64(signing_key)),
            'data': ('DV_DATA_KEYS', f'{kid}={signing.b64encode(os.urandom(AES_KEY_BYTES))}'),
            'vault': ('DV_VAULT_KEYS', f'{kid}={ecies.private_key_to_b64(ecies.generate_private_key())}'),
        }
        if only:
            self.stdout.write(values[only][1])
        else:
            for name, value in values.values():
                self.stdout.write(f'{name}={value}')
        if only in (None, 'signing'):
            self.stderr.write(
                f'Signing key fingerprint: {signing.fingerprint(signing.public_key_to_b64(signing_key))}. '
                'Workers pin it when first approved, so changing it later means resetting every worker.'
            )
        self.stderr.write(
            'Every orchestrator node needs the same keys. To rotate a data or vault key, put the new '
            'kid=value first and keep the old one after it while anything encrypted with it remains.'
        )
