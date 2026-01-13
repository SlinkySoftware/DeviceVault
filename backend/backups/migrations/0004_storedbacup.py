# Generated manually for StoredBackup model
from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):

    dependencies = [
        ('devices', '0016_devicebackupresult'),
        ('backups', '0003_backup_completed_at_backup_requested_at_and_more'),
    ]

    operations = [
        migrations.CreateModel(
            name='StoredBackup',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('task_id', models.CharField(db_index=True, max_length=64)),
                ('task_identifier', models.CharField(db_index=True, max_length=128)),
                ('storage_backend', models.CharField(db_index=True, max_length=32)),
                ('storage_ref', models.CharField(max_length=256)),
                ('status', models.CharField(max_length=16)),
                ('timestamp', models.DateTimeField()),
                ('log', models.TextField(help_text='JSON serialized list of log messages')),
                ('device', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, to='devices.device')),
            ],
            options={'ordering': ['-timestamp']},
        ),
    ]
