# Migration to update DeviceGroupDjangoPermissions structure

from django.db import migrations, models
import django.db.models.deletion


def delete_old_permissions_and_mappings(apps, schema_editor):
    """Delete old permission mappings and let signals recreate them"""
    # Just delete the old DeviceGroupDjangoPermissions records
    # The post_save signal will recreate them with the new structure
    cursor = schema_editor.connection.cursor()
    cursor.execute('DELETE FROM devices_devicegroupdjangopermissions')


def reverse_migration(apps, schema_editor):
    """Reverse operation - does nothing since signals will handle it"""
    pass


class Migration(migrations.Migration):

    dependencies = [
        ('devices', '0006_move_devicegroup_from_rbac'),
    ]

    operations = [
        # Step 1: Delete old mappings
        migrations.RunPython(delete_old_permissions_and_mappings, reverse_migration),
        
        # Step 2: Remove old fields
        migrations.RemoveField(
            model_name='devicegroupdjangopermissions',
            name='perm_add',
        ),
        migrations.RemoveField(
            model_name='devicegroupdjangopermissions',
            name='perm_change',
        ),
        migrations.RemoveField(
            model_name='devicegroupdjangopermissions',
            name='perm_delete',
        ),
        
        # Step 3: Add new fields
        migrations.AddField(
            model_name='devicegroupdjangopermissions',
            name='perm_modify',
            field=models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name='dg_perm_modify', to='auth.permission', default=1),
            preserve_default=False,
        ),
        migrations.AddField(
            model_name='devicegroupdjangopermissions',
            name='perm_view_backups',
            field=models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name='dg_perm_view_backups', to='auth.permission', default=1),
            preserve_default=False,
        ),
    ]
