# Migration to remove legacy RBAC models
from django.db import migrations


def remove_legacy_tables(apps, schema_editor):
    """Use raw SQL to drop legacy tables"""
    with schema_editor.connection.cursor() as cursor:
        # Check and drop tables if they exist
        tables_to_drop = ['rbac_userrole', 'rbac_role_permissions', 'rbac_role_labels', 'rbac_role', 'rbac_permission']
        
        for table in tables_to_drop:
            try:
                cursor.execute(f"DROP TABLE IF EXISTS {table}")
                print(f"  ✓ Dropped table {table}")
            except Exception as e:
                print(f"  ✗ Could not drop {table}: {e}")


class Migration(migrations.Migration):

    dependencies = [
        ('rbac', '0008_remove_devicegroup_models'),
    ]

    operations = [
        migrations.RunPython(remove_legacy_tables, reverse_code=migrations.RunPython.noop),
    ]
