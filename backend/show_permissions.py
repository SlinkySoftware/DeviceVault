#!/usr/bin/env python
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
