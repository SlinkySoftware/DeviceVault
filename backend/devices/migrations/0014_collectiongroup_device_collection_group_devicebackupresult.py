# Generated migration for Celery collection infrastructure

from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):

    dependencies = [
        ('devices', '0013_ensure_devicegroup_tables'),
    ]

    operations = [
        # Create CollectionGroup model for task routing
        migrations.CreateModel(
            name='CollectionGroup',
            fields=[
                ('id', models.AutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('name', models.CharField(help_text='Unique collection group identifier (e.g., us-west-collectors)', max_length=64, unique=True)),
                ('description', models.TextField(blank=True, help_text='Description of this collector group purpose and scope')),
                ('queue_name', models.CharField(blank=True, default='', help_text='Celery queue name (auto-derived from name if blank)', max_length=128)),
                ('created_at', models.DateTimeField(auto_now_add=True)),
                ('updated_at', models.DateTimeField(auto_now=True)),
            ],
            options={
                'ordering': ['name'],
            },
        ),
        
        # Add collection_group ForeignKey to Device
        migrations.AddField(
            model_name='device',
            name='collection_group',
            field=models.ForeignKey(blank=True, help_text='Collection group for task routing (routes to collector.group.<name> queue)', null=True, on_delete=django.db.models.deletion.SET_NULL, to='devices.collectiongroup'),
        ),
        
        # Create DeviceBackupResult model for task result storage
        migrations.CreateModel(
            name='DeviceBackupResult',
            fields=[
                ('id', models.AutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('task_id', models.CharField(db_index=True, help_text='Celery task UUID for tracing', max_length=64)),
                ('task_identifier', models.CharField(db_index=True, help_text='Unique identifier for external device_config lookup: device_id:task_id', max_length=128)),
                ('status', models.CharField(choices=[('success', 'Success'), ('failure', 'Failure'), ('pending', 'Pending'), ('revoked', 'Revoked')], help_text='Collection task status', max_length=16)),
                ('timestamp', models.DateTimeField(help_text='When collection task completed')),
                ('log', models.TextField(help_text='JSON-serialized list of log messages')),
                ('device', models.ForeignKey(help_text='Device that was backed up', on_delete=django.db.models.deletion.CASCADE, related_name='backup_results', to='devices.device')),
            ],
            options={
                'verbose_name_plural': 'Device Backup Results',
                'ordering': ['-timestamp'],
            },
        ),
        
        # Add indexes for DeviceBackupResult
        migrations.AddIndex(
            model_name='devicebackupresult',
            index=models.Index(fields=['task_id'], name='devices_devi_task_id_idx'),
        ),
        migrations.AddIndex(
            model_name='devicebackupresult',
            index=models.Index(fields=['task_identifier'], name='devices_devi_task_id_b6a7f3_idx'),
        ),
        migrations.AddIndex(
            model_name='devicebackupresult',
            index=models.Index(fields=['device'], name='devices_devi_device_idx'),
        ),
        migrations.AddIndex(
            model_name='devicebackupresult',
            index=models.Index(fields=['-timestamp'], name='devices_devi_timestam_idx'),
        ),
    ]
