#!/usr/bin/env python
"""
DeviceVault - A comprehensive network device backup management application with web interface for user and admin access and backend component for automated backup collection.
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

"""Show all Django permissions"""
import os
import django

os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'devicevault.settings')
django.setup()

from django.contrib.auth.models import Permission
from django.contrib.contenttypes.models import ContentType

perms = Permission.objects.select_related('content_type').order_by(
    'content_type__app_label', 'content_type__model', 'codename'
)

print(f"Total permissions: {perms.count()}\n")
print(f"{'App':<20} | {'Model':<20} | {'Codename':<50} | Name")
print("=" * 140)

for p in perms:
    print(f"{p.content_type.app_label:<20} | {p.content_type.model:<20} | {p.codename:<50} | {p.name}")
