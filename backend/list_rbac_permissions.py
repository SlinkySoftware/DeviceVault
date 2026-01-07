#!/usr/bin/env python
"""List all RBAC app permissions grouped by model"""
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
