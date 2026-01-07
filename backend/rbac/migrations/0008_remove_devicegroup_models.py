# Migration to remove DeviceGroup models from rbac app state
# Uses SeparateDatabaseAndState to avoid touching the database

from django.db import migrations


class Migration(migrations.Migration):

    dependencies = [
        ('rbac', '0007_devicegroupdjangopermissions_and_more'),
        ('devices', '0006_move_devicegroup_from_rbac'),
    ]

    # Don't touch the database - tables now belong to devices app
    database_operations = []

    # Remove these models from rbac app state
    state_operations = [
        migrations.DeleteModel(name='DeviceGroupDjangoPermissions'),
        migrations.DeleteModel(name='GroupDeviceGroupRole'),
        migrations.DeleteModel(name='UserDeviceGroupRole'),
        migrations.DeleteModel(name='DeviceGroupRole'),
        migrations.DeleteModel(name='DeviceGroupPermission'),
        migrations.DeleteModel(name='DeviceGroup'),
    ]

    operations = [
        migrations.SeparateDatabaseAndState(
            database_operations=database_operations,
            state_operations=state_operations,
        )
    ]
