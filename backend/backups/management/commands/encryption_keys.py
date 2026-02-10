"""
Django management command for encryption key management.

Usage:
    python manage.py encryption_keys list
    python manage.py encryption_keys generate
    python manage.py encryption_keys set-default <kid>
    python manage.py encryption_keys rewrap --from <old_kid> --to <new_kid>
    python manage.py encryption_keys status

Copyright (C) 2026, Slinky Software
License: GPLv3+
"""

from django.core.management.base import BaseCommand, CommandError


class Command(BaseCommand):
    help = 'Manage DeviceVault backup encryption keys'

    def add_arguments(self, parser):
        subparsers = parser.add_subparsers(dest='subcommand', help='Key management sub-commands')

        # list
        subparsers.add_parser('list', help='List all key IDs in the key ring')

        # generate
        subparsers.add_parser('generate', help='Generate a new random 256-bit master key (base64)')

        # set-default
        sp_default = subparsers.add_parser('set-default', help='Set the default key ID for new encryptions')
        sp_default.add_argument('kid', type=str, help='Key ID to set as default')

        # rewrap
        sp_rewrap = subparsers.add_parser('rewrap', help='Re-wrap existing EDKs from one master key to another')
        sp_rewrap.add_argument('--from-kid', required=True, help='Source KID (old master key)')
        sp_rewrap.add_argument('--to-kid', required=True, help='Target KID (new master key)')
        sp_rewrap.add_argument('--dry-run', action='store_true', help='Show what would be re-wrapped without changing data')

        # status
        subparsers.add_parser('status', help='Show encryption configuration status')

    def handle(self, *args, **options):
        subcommand = options.get('subcommand')
        if not subcommand:
            self.stderr.write(self.style.ERROR('Please specify a sub-command: list, generate, set-default, rewrap, status'))
            return

        handler = getattr(self, f'_handle_{subcommand.replace("-", "_")}', None)
        if handler is None:
            raise CommandError(f'Unknown sub-command: {subcommand}')
        handler(options)

    def _handle_list(self, options):
        """List all KIDs in the key ring."""
        kp = self._get_provider()
        kids = kp.list_key_ids()
        default = kp.get_default_key_id()

        self.stdout.write(self.style.SUCCESS(f'Key ring contains {len(kids)} key(s):'))
        for kid in kids:
            marker = ' (default)' if kid == default else ''
            self.stdout.write(f'  • {kid}{marker}')

        # Show per-KID backup counts
        from backups.models import StoredBackup
        for kid in kids:
            count = StoredBackup.objects.filter(enc_kid=kid).count()
            self.stdout.write(f'    Backups encrypted with {kid}: {count}')

    def _handle_generate(self, options):
        """Generate a new random master key."""
        from crypto.providers import LocalKeyProvider
        key_b64 = LocalKeyProvider.generate_master_key()
        self.stdout.write(self.style.SUCCESS('Generated new 256-bit master key:'))
        self.stdout.write(f'  {key_b64}')
        self.stdout.write('')
        self.stdout.write('Add this to config.yaml under encryption.keys:')
        self.stdout.write('  encryption:')
        self.stdout.write('    keys:')
        self.stdout.write(f'      new-key-id: {key_b64}')

    def _handle_set_default(self, options):
        """Set the default KID."""
        kid = options['kid']
        kp = self._get_provider()

        if kid not in kp.list_key_ids():
            raise CommandError(f'KID "{kid}" not found in key ring. Available: {kp.list_key_ids()}')

        old_default = kp.get_default_key_id()
        kp.set_default_key_id(kid)
        self.stdout.write(self.style.SUCCESS(f'Default KID changed: {old_default} -> {kid}'))
        self.stdout.write(self.style.WARNING(
            'Note: This change is runtime-only. To persist, update '
            'encryption.default_key_id in config.yaml.'
        ))

    def _handle_rewrap(self, options):
        """Re-wrap EDKs from one master key to another."""
        from_kid = options['from_kid']
        to_kid = options['to_kid']
        dry_run = options.get('dry_run', False)

        kp = self._get_provider()
        available = kp.list_key_ids()

        if from_kid not in available:
            raise CommandError(f'Source KID "{from_kid}" not in key ring. Available: {available}')
        if to_kid not in available:
            raise CommandError(f'Target KID "{to_kid}" not in key ring. Available: {available}')
        if from_kid == to_kid:
            raise CommandError('Source and target KID are the same — nothing to rewrap')

        from backups.models import StoredBackup
        import base64

        backups = StoredBackup.objects.filter(enc_kid=from_kid, enc_edk__isnull=False).exclude(enc_edk='')
        total = backups.count()

        if total == 0:
            self.stdout.write(self.style.WARNING(f'No backups found encrypted with KID "{from_kid}"'))
            return

        self.stdout.write(f'Found {total} backup(s) to re-wrap from "{from_kid}" to "{to_kid}"')

        if dry_run:
            self.stdout.write(self.style.WARNING('Dry run — no changes will be made'))
            return

        # Temporarily set default to target KID for wrapping
        original_default = kp.get_default_key_id()
        kp.set_default_key_id(to_kid)

        rewrapped = 0
        errors = 0

        for sb in backups.iterator():
            try:
                # Decode existing EDK
                edk_bytes = base64.b64decode(sb.enc_edk)

                # Unwrap with old key
                plaintext_dek = kp.unwrap_key(edk_bytes, from_kid)

                # Wrap with new key
                new_edk, new_kid = kp.wrap_key(plaintext_dek)

                # Zeroize plaintext DEK
                if isinstance(plaintext_dek, bytearray):
                    for i in range(len(plaintext_dek)):
                        plaintext_dek[i] = 0

                # Update record
                sb.enc_edk = base64.b64encode(new_edk).decode('ascii')
                sb.enc_kid = new_kid
                sb.save(update_fields=['enc_edk', 'enc_kid'])
                rewrapped += 1

            except Exception as exc:
                errors += 1
                self.stderr.write(self.style.ERROR(
                    f'Failed to re-wrap backup {sb.pk} ({sb.task_identifier}): {exc}'
                ))

        # Restore original default
        kp.set_default_key_id(original_default)

        self.stdout.write(self.style.SUCCESS(
            f'Re-wrap complete: {rewrapped} succeeded, {errors} failed'
        ))

    def _handle_status(self, options):
        """Show encryption configuration status."""
        from crypto.config import (
            get_encryption_enabled,
            get_chunk_size,
            get_allow_plaintext_fallback,
        )

        enabled = get_encryption_enabled()
        chunk_size = get_chunk_size()
        allow_fallback = get_allow_plaintext_fallback()

        self.stdout.write(self.style.SUCCESS('Encryption Configuration:'))
        self.stdout.write(f'  Enabled: {enabled}')
        self.stdout.write(f'  Chunk size: {chunk_size:,} bytes ({chunk_size // 1024} KiB)')
        self.stdout.write(f'  Allow plaintext fallback: {allow_fallback}')

        if enabled:
            try:
                kp = self._get_provider()
                kids = kp.list_key_ids()
                default = kp.get_default_key_id()
                self.stdout.write(f'  Key provider: local')
                self.stdout.write(f'  Key ring: {len(kids)} key(s)')
                self.stdout.write(f'  Default KID: {default}')
            except Exception as exc:
                self.stdout.write(self.style.ERROR(f'  Key provider: FAILED ({exc})'))

        # Database stats
        from backups.models import StoredBackup
        total = StoredBackup.objects.count()
        encrypted = StoredBackup.objects.filter(enc_version__gt=0).count()
        plaintext = total - encrypted
        self.stdout.write(f'  Total stored backups: {total}')
        self.stdout.write(f'  Encrypted (v1+): {encrypted}')
        self.stdout.write(f'  Plaintext (v0): {plaintext}')

    def _get_provider(self):
        """Get the key provider or raise CommandError."""
        from crypto.config import get_key_provider, get_encryption_enabled
        from crypto.exceptions import KeyProviderError

        if not get_encryption_enabled():
            raise CommandError(
                'Encryption is not enabled. Set encryption.enabled: true in '
                'config.yaml or DEVICEVAULT_ENCRYPTION_ENABLED=true'
            )

        try:
            kp = get_key_provider()
        except KeyProviderError as exc:
            raise CommandError(f'Failed to initialise key provider: {exc}')

        if kp is None:
            raise CommandError('Key provider is not available')

        return kp
