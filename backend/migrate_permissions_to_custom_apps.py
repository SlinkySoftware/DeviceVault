#!/usr/bin/env python
"""
Migrate Django permissions to custom app namespaces for better organization.
"""
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

from django.contrib.auth.models import Permission, User, Group
from django.contrib.contenttypes.models import ContentType
from django.db import transaction

# Define the migration mapping
PERMISSION_MIGRATIONS = {
    'dv_user': [
        ('auth', 'user'),
        ('auth', 'group'),
    ],
    'dv_devices': [
        ('devices', 'devicetype'),
        ('devices', 'manufacturer'),
        ('devices', 'device'),
    ],
    'dv_backups': [
        ('credentials', 'credential'),
        ('credentials', 'credentialtype'),
        ('locations', 'backuplocation'),
        ('policies', 'backupschedule'),
        ('policies', 'retentionpolicy'),
        ('backups', 'backup'),
    ],
}

def migrate_permissions():
    """Migrate permissions to custom app namespaces."""
    
    with transaction.atomic():
        for new_app_label, model_list in PERMISSION_MIGRATIONS.items():
            print(f"\n{'='*80}")
            print(f"Processing app: {new_app_label}")
            print(f"{'='*80}")
            
            for old_app_label, model_name in model_list:
                print(f"\nMigrating {old_app_label}.{model_name}...")
                
                # Get the old content type
                try:
                    old_ct = ContentType.objects.get(app_label=old_app_label, model=model_name)
                except ContentType.DoesNotExist:
                    print(f"  ⚠ Content type {old_app_label}.{model_name} not found, skipping")
                    continue
                
                # Get or create new content type
                new_ct, created = ContentType.objects.get_or_create(
                    app_label=new_app_label,
                    model=model_name
                )
                if created:
                    print(f"  ✓ Created new content type: {new_app_label}.{model_name}")
                else:
                    print(f"  • Content type {new_app_label}.{model_name} already exists")
                
                # Get all old permissions
                old_perms = Permission.objects.filter(content_type=old_ct)
                print(f"  Found {old_perms.count()} permissions to migrate")
                
                for old_perm in old_perms:
                    # Create new permission with same codename and name
                    new_perm, perm_created = Permission.objects.get_or_create(
                        content_type=new_ct,
                        codename=old_perm.codename,
                        defaults={'name': old_perm.name}
                    )
                    
                    if perm_created:
                        print(f"    ✓ Created: {new_perm.codename}")
                        
                        # Migrate user permissions
                        users_with_old = User.objects.filter(user_permissions=old_perm)
                        for user in users_with_old:
                            user.user_permissions.add(new_perm)
                        if users_with_old.count() > 0:
                            print(f"      → Migrated {users_with_old.count()} user assignments")
                        
                        # Migrate group permissions
                        groups_with_old = Group.objects.filter(permissions=old_perm)
                        for group in groups_with_old:
                            group.permissions.add(new_perm)
                        if groups_with_old.count() > 0:
                            print(f"      → Migrated {groups_with_old.count()} group assignments")
                    else:
                        print(f"    • Already exists: {new_perm.codename}")
                
                # Remove old permissions (after migration)
                print(f"  Removing {old_perms.count()} old permissions...")
                old_perms.delete()
                
                # Remove old content type if no permissions left
                if not Permission.objects.filter(content_type=old_ct).exists():
                    print(f"  ✓ Removed old content type: {old_app_label}.{model_name}")
                    old_ct.delete()
        
        print(f"\n{'='*80}")
        print("Migration complete!")
        print(f"{'='*80}\n")

if __name__ == '__main__':
    print("This will migrate permissions to custom app namespaces.")
    print("\nMigration plan:")
    for new_app, models in PERMISSION_MIGRATIONS.items():
        print(f"\n  {new_app}:")
        for old_app, model in models:
            print(f"    - {old_app}.{model}")
    
    response = input("\n⚠ Proceed with migration? (yes/no): ")
    if response.lower() == 'yes':
        migrate_permissions()
        print("\n✓ Done! Run show_permissions.py to verify the changes.")
    else:
        print("Migration cancelled.")
