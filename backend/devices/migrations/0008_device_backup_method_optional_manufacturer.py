# Generated manually to add backup_method and make manufacturer optional
from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):

    dependencies = [
        ('devices', '0007_update_devicegroup_permissions'),
    ]

    operations = [
        migrations.AddField(
            model_name='device',
            name='backup_method',
            field=models.CharField(default='noop', max_length=128, help_text='Backup plugin key to use for this device'),
        ),
        migrations.AlterField(
            model_name='device',
            name='manufacturer',
            field=models.ForeignKey(blank=True, help_text='Hardware manufacturer (optional)', null=True, on_delete=django.db.models.deletion.PROTECT, to='devices.manufacturer'),
        ),
    ]
