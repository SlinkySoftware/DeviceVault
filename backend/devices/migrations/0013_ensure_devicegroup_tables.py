from django.db import migrations


def ensure_device_group_tables(apps, schema_editor):
    connection = schema_editor.connection
    existing_tables = set(connection.introspection.table_names())

    model_names = [
        'DeviceGroup',
        'DeviceGroupPermission',
        'DeviceGroupRole',
        'UserDeviceGroupRole',
        'GroupDeviceGroupRole',
        'DeviceGroupDjangoPermissions',
    ]

    for name in model_names:
        model = apps.get_model('devices', name)
        table = model._meta.db_table
        if table not in existing_tables:
            schema_editor.create_model(model)
            existing_tables.add(table)


def noop_reverse(apps, schema_editor):
    # No-op reverse; we don't drop tables on rollback to avoid data loss.
    pass


class Migration(migrations.Migration):

    dependencies = [
        ('devices', '0012_alter_devicegroup_options_and_more'),
    ]

    operations = [
        migrations.RunPython(ensure_device_group_tables, reverse_code=noop_reverse),
    ]
