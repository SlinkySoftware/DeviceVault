# Migration to move DeviceGroup models from rbac to devices app
# Uses SeparateDatabaseAndState to avoid recreating tables

from django.db import migrations, models
from django.utils import timezone
import django.db.models.deletion
from django.conf import settings


class Migration(migrations.Migration):

    dependencies = [
            ('devices', '0005_remove_device_labels'),
            migrations.swappable_dependency(settings.AUTH_USER_MODEL),
            ('auth', '0012_alter_user_first_name_max_length'),
            ('contenttypes', '0002_remove_content_type_name'),
    ]

    # Define the exact database table names from rbac
    database_operations = []

    # Update Django's state to show these models now belong to devices app
    state_operations = [
        migrations.CreateModel(
            name='DeviceGroup',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('name', models.CharField(max_length=100, unique=True)),
                ('description', models.TextField(blank=True)),
                ('created_at', models.DateTimeField(auto_now_add=True)),
                ('updated_at', models.DateTimeField(auto_now=True)),
            ],
            options={
                    'db_table': 'devices_devicegroup',
                'ordering': ['name'],
            },
        ),
        migrations.CreateModel(
            name='DeviceGroupPermission',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('code', models.CharField(max_length=50, unique=True)),
                ('name', models.CharField(max_length=100)),
                ('description', models.TextField(blank=True)),
            ],
            options={
                    'db_table': 'devices_devicegrouppermission',
                'ordering': ['code'],
            },
        ),
        migrations.CreateModel(
            name='DeviceGroupRole',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('name', models.CharField(max_length=100)),
                ('created_at', models.DateTimeField(blank=True, null=True, default=timezone.now)),
                ('description', models.TextField(blank=True)),
                ('device_group', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name='roles', to='devices.devicegroup')),
                ('permissions', models.ManyToManyField(blank=True, related_name='roles', to='devices.devicegrouppermission')),
            ],
            options={
                    'db_table': 'devices_devicegrouprole',
                'ordering': ['device_group', 'name'],
                'unique_together': {('device_group', 'name')},
            },
        ),
        migrations.CreateModel(
            name='UserDeviceGroupRole',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('user', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name='device_group_roles', to=settings.AUTH_USER_MODEL)),
                ('role', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name='user_assignments', to='devices.devicegrouprole')),
            ],
            options={
                    'db_table': 'devices_userdevicegrouprole',
                'unique_together': {('user', 'role')},
            },
        ),
        migrations.CreateModel(
            name='GroupDeviceGroupRole',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('auth_group', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name='device_group_roles', to='auth.group')),
                ('role', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name='group_assignments', to='devices.devicegrouprole')),
            ],
            options={
                    'db_table': 'devices_groupdevicegrouprole',
                'unique_together': {('auth_group', 'role')},
            },
        ),
        migrations.CreateModel(
            name='DeviceGroupDjangoPermissions',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('device_group', models.OneToOneField(on_delete=django.db.models.deletion.CASCADE, related_name='django_permissions', to='devices.devicegroup')),
                ('perm_view', models.ForeignKey(blank=True, default=None, null=True, on_delete=django.db.models.deletion.CASCADE, related_name='dg_perm_view', to='auth.permission')),
                ('perm_modify', models.ForeignKey(blank=True, default=None, null=True, on_delete=django.db.models.deletion.CASCADE, related_name='dg_perm_modify', to='auth.permission')),
                ('perm_view_backups', models.ForeignKey(blank=True, default=None, null=True, on_delete=django.db.models.deletion.CASCADE, related_name='dg_perm_view_backups', to='auth.permission')),
            ],
            options={
                    'db_table': 'devices_devicegroupdjangopermissions',
            },
        ),
        # Update Device.device_group FK to point to devices.DeviceGroup instead of rbac.DeviceGroup
        migrations.AlterField(
            model_name='device',
            name='device_group',
            field=models.ForeignKey(
                blank=True,
                null=True,
                on_delete=django.db.models.deletion.PROTECT,
                related_name='devices',
                to='devices.devicegroup'
            ),
        ),
    ]

    operations = [
        migrations.SeparateDatabaseAndState(
            database_operations=database_operations,
            state_operations=state_operations,
        )
    ]
