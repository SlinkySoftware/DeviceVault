#!/usr/bin/env python
"""
Migrate DeviceGroup-related Django permissions from rbac app to devices app.
This uses direct SQL to avoid Django's transaction and FK issues.
"""
import os
import django

os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'devicevault.settings')
django.setup()

from django.db import connection

# Models to migrate from rbac to devices
MODELS_TO_MIGRATE = [
    'devicegroup',
    'devicegrouppermission',
    'devicegrouprole',
    'userdevicegrouprole',
    'groupdevicegrouprole',
    'devicegroupdjangopermissions',
]

def migrate_permissions_raw_sql():
    """Migrate using raw SQL to avoid FK issues."""
    
    cursor = connection.cursor()
    
    print("="*80)
    print("Migrating DeviceGroup permissions from rbac to devices app (Raw SQL)")
    print("="*80)
    
    for model_name in MODELS_TO_MIGRATE:
        print(f"\nProcessing {model_name}...")
        
        # Get old and new content type IDs
        cursor.execute("""
            SELECT id FROM django_content_type 
            WHERE app_label = 'rbac' AND model = %s
        """, [model_name])
        old_ct_row = cursor.fetchone()
        
        if not old_ct_row:
            print(f"  ⚠ Content type rbac.{model_name} not found, skipping")
            continue
            
        old_ct_id = old_ct_row[0]
        
        cursor.execute("""
            SELECT id FROM django_content_type 
            WHERE app_label = 'devices' AND model = %s
        """, [model_name])
        new_ct_row = cursor.fetchone()
        
        if not new_ct_row:
            print(f"  ✗ Content type devices.{model_name} not found!")
            continue
            
        new_ct_id = new_ct_row[0]
        
        # Get old permissions
        cursor.execute("""
            SELECT id, codename, name FROM auth_permission 
            WHERE content_type_id = %s
        """, [old_ct_id])
        old_perms = cursor.fetchall()
        
        print(f"  Found {len(old_perms)} permissions to migrate")
        
        for old_perm_id, codename, name in old_perms:
            # Get or find new permission
            cursor.execute("""
                SELECT id FROM auth_permission 
                WHERE content_type_id = %s AND codename = %s
            """, [new_ct_id, codename])
            new_perm_row = cursor.fetchone()
            
            if new_perm_row:
                new_perm_id = new_perm_row[0]
            else:
                # Create new permission
                cursor.execute("""
                    INSERT INTO auth_permission (content_type_id, codename, name)
                    VALUES (%s, %s, %s)
                """, [new_ct_id, codename, name])
                new_perm_id = cursor.lastrowid
                print(f"    ✓ Created permission: {codename}")
            
            # Migrate group permissions
            cursor.execute("""
                UPDATE auth_group_permissions 
                SET permission_id = %s 
                WHERE permission_id = %s
            """, [new_perm_id, old_perm_id])
            if cursor.rowcount > 0:
                print(f"    ✓ Updated {cursor.rowcount} group permission(s) for {codename}")
            
            # Migrate user permissions
            cursor.execute("""
                UPDATE auth_user_user_permissions 
                SET permission_id = %s 
                WHERE permission_id = %s
            """, [new_perm_id, old_perm_id])
            if cursor.rowcount > 0:
                print(f"    ✓ Updated {cursor.rowcount} user permission(s) for {codename}")
            
            # For devicegroup model, also update DeviceGroupDjangoPermissions FKs
            if model_name == 'devicegroup':
                for perm_field in ['perm_add_id', 'perm_change_id', 'perm_delete_id', 'perm_view_id']:
                    cursor.execute(f"""
                        UPDATE rbac_devicegroupdjangopermissions 
                        SET {perm_field} = %s 
                        WHERE {perm_field} = %s
                    """, [new_perm_id, old_perm_id])
                    if cursor.rowcount > 0:
                        print(f"    ✓ Updated {cursor.rowcount} rbac_devicegroupdjangopermissions.{perm_field}")
            
            # Delete old permission
            cursor.execute("DELETE FROM auth_permission WHERE id = %s", [old_perm_id])
        
        # Delete old content type
        cursor.execute("DELETE FROM django_content_type WHERE id = %s", [old_ct_id])
        print(f"  ✓ Removed old content type: rbac.{model_name}")
    
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
        migrate_permissions_raw_sql()
        print("\n✓ Done! DeviceGroup permissions now under devices app.")
    else:
        print("Migration cancelled.")
