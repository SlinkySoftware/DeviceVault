#!/usr/bin/env python
"""
Migrate DeviceGroup-related Django permissions from rbac app to devices app.
This includes all DeviceGroup models and their related permissions.
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

# Models to migrate from rbac to devices
MODELS_TO_MIGRATE = [
    'devicegroup',
    'devicegrouppermission',
    'devicegrouprole',
    'userdevicegrouprole',
    'groupdevicegrouprole',
    'devicegroupdjangopermissions',
]

def migrate_rbac_to_devices():
    """Migrate DeviceGroup-related permissions from rbac to devices app."""
    
    with transaction.atomic():
        print("="*80)
        print("Migrating DeviceGroup permissions from rbac to devices app")
        print("="*80)
        
        for model_name in MODELS_TO_MIGRATE:
            print(f"\nProcessing {model_name}...")
            
            # Get old content type
            try:
                old_ct = ContentType.objects.get(app_label='rbac', model=model_name)
            except ContentType.DoesNotExist:
                print(f"  ⚠ Content type rbac.{model_name} not found, skipping")
                continue
            
            # Get or create new content type
            new_ct, created = ContentType.objects.get_or_create(
                app_label='devices',
                model=model_name
            )
            if created:
                print(f"  ✓ Created new content type: devices.{model_name}")
            else:
                print(f"  • Content type devices.{model_name} already exists")
            
            # Get all old permissions
            old_perms = Permission.objects.filter(content_type=old_ct)
            perm_count = old_perms.count()
            print(f"  Found {perm_count} permissions to migrate")
            
            migrated = 0
            for old_perm in old_perms:
                # Create new permission
                new_perm, perm_created = Permission.objects.get_or_create(
                    content_type=new_ct,
                    codename=old_perm.codename,
                    defaults={'name': old_perm.name}
                )
                
                if perm_created:
                    migrated += 1
                    
                    # Migrate user permissions
                    users_with_old = User.objects.filter(user_permissions=old_perm)
                    for user in users_with_old:
                        user.user_permissions.add(new_perm)
                        user.user_permissions.remove(old_perm)
                    
                    # Migrate group permissions
                    groups_with_old = Group.objects.filter(permissions=old_perm)
                    for group in groups_with_old:
                        group.permissions.add(new_perm)
                        group.permissions.remove(old_perm)
                    
                    # Update DeviceGroupDjangoPermissions FK references if this is devicegroup model
                    if model_name == 'devicegroup':
                        from devices.models import DeviceGroupDjangoPermissions
                        
                        # Update each FK field that points to old permission
                        if 'add' in old_perm.codename:
                            DeviceGroupDjangoPermissions.objects.filter(perm_add=old_perm).update(perm_add=new_perm)
                        elif 'change' in old_perm.codename:
                            DeviceGroupDjangoPermissions.objects.filter(perm_change=old_perm).update(perm_change=new_perm)
                        elif 'delete' in old_perm.codename:
                            DeviceGroupDjangoPermissions.objects.filter(perm_delete=old_perm).update(perm_delete=new_perm)
                        elif 'view' in old_perm.codename:
                            DeviceGroupDjangoPermissions.objects.filter(perm_view=old_perm).update(perm_view=new_perm)
            
            if migrated > 0:
                print(f"  ✓ Migrated {migrated} permissions")
            
            # Now safe to remove old permissions
            print(f"  Removing {perm_count} old permissions...")
            old_perms.delete()
            
            # Remove old content type
            if not Permission.objects.filter(content_type=old_ct).exists():
                print(f"  ✓ Removed old content type: rbac.{model_name}")
                old_ct.delete()
        
        print(f"\n{'='*80}")
        print("Migration complete!")
        print(f"{'='*80}\n")

if __name__ == '__main__':
    print("\nThis will migrate DeviceGroup-related permissions from rbac to devices app.")
    print("\nModels to migrate:")
    for model in MODELS_TO_MIGRATE:
        print(f"  - {model}")
    
    response = input("\n⚠ Proceed with migration? (yes/no): ")
    if response.lower() == 'yes':
        migrate_rbac_to_devices()
        print("\n✓ Done! DeviceGroup permissions now under devices app.")
    else:
        print("Migration cancelled.")
