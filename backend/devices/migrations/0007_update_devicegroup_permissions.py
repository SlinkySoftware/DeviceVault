# Migration to update DeviceGroupDjangoPermissions structure
# This migration is now a no-op as the model state is handled by earlier migrations

from django.db import migrations


class Migration(migrations.Migration):

    dependencies = [
        ('devices', '0006_move_devicegroup_from_rbac'),
    ]

    operations = []
