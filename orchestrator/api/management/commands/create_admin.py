"""
Management command: create default admin user for DeviceVault

Copyright (C) 2026, Slinky Software

This program is free software: you can redistribute it and/or modify
it under the terms of the GNU General Public License as published by
the Free Software Foundation, either version 3 of the License, or
(at your option) any later version.

This program is distributed in the hope that it will be useful,
but WITHOUT ANY WARRANTY; without even the implied warranty of
MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
GNU General Public License for more details.

You should have received a copy of the GNU General Public License
along with this program.  If not, see <http://www.gnu.org/licenses/>.
"""

from django.contrib.auth.models import User
from django.core.management.base import BaseCommand, CommandError
from django.db import transaction

from accounts.access import active_global_admins, administrators_group
from accounts.models import UserGroupMembership
from devicevault_protocol.env import env_str


class Command(BaseCommand):
    help = (
        'Create the built-in Administrators group, and the bootstrap admin user in it if that user does not exist '
        '(DV_ADMIN_USERNAME / DV_ADMIN_PASSWORD). An existing bootstrap user is added to Administrators only '
        'while there is no active global administrator, so it cannot be locked out.'
    )

    def add_arguments(self, parser):
        parser.add_argument('--username', type=str, help='Admin username (default: DV_ADMIN_USERNAME or admin)')
        parser.add_argument('--password', type=str, help='Admin password (default: DV_ADMIN_PASSWORD)')
        parser.add_argument('--email', type=str, help='Admin email (default: DV_ADMIN_EMAIL)')

    def handle(self, *args, **options):
        username = options['username'] or env_str('DV_ADMIN_USERNAME', 'admin')
        password = options['password'] or env_str('DV_ADMIN_PASSWORD')
        email = options['email'] or env_str('DV_ADMIN_EMAIL', '')

        administrators = administrators_group()
        existing = User.objects.filter(username=username).first()
        if existing is not None:
            if not active_global_admins().exists():
                existing.is_active = True
                existing.save(update_fields=['is_active'])
                UserGroupMembership.objects.get_or_create(user=existing, group=administrators)
                self.stdout.write(self.style.WARNING(f'No active global administrator: added "{username}" to them'))
            else:
                self.stdout.write(f'Admin user "{username}" already exists')
            return
        if not password:
            raise CommandError('Set DV_ADMIN_PASSWORD (or pass --password) to create the bootstrap admin user')

        with transaction.atomic():
            user = User.objects.create_user(username, email, password)
            UserGroupMembership.objects.create(user=user, group=administrators)
        self.stdout.write(self.style.SUCCESS(f'Created admin user "{username}"'))
