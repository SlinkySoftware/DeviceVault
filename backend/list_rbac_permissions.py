#!/usr/bin/env python
"""List all RBAC app permissions grouped by model"""
# DeviceVault - A comprehensive network device backup management application with web interface for user and admin access and backend component for automated backup collection.
# Copyright (C) 2026, Slinky Software
#
# This program is free software: you can redistribute it and/or modify
# it under the terms of the GNU General Public License as published by
# the Free Software Foundation, either version 3 of the License, or
# (at your option) any later version.
#
# This program is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
# GNU General Public License for more details.
#
# You should have received a copy of the GNU General Public License
# along with this program.  If not, see <http://www.gnu.org/licenses/>.

import os
import django

os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'devicevault.settings')
django.setup()

from django.contrib.auth.models import Permission
from django.contrib.contenttypes.models import ContentType

rbac_perms = Permission.objects.filter(
    content_type__app_label='rbac'
).order_by('content_type__model', 'codename')

print('RBAC app permissions by model:\n')
print('='*80)

current_model = None
for p in rbac_perms:
    if p.content_type.model != current_model:
        current_model = p.content_type.model
        print(f'\n{current_model.upper()}:')
    print(f'  {p.codename:<50} | {p.name}')

print(f'\n{"="*80}')
print(f'Total RBAC permissions: {rbac_perms.count()}')
