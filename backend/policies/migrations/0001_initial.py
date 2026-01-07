# Initial migration for policies app

from django.db import migrations, models


class Migration(migrations.Migration):

    initial = True

    dependencies = [
    ]

    operations = [
        migrations.CreateModel(
            name='RetentionPolicy',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('name', models.CharField(max_length=128)),
                ('max_backups', models.IntegerField(blank=True, null=True)),
                ('max_days', models.IntegerField(blank=True, null=True)),
                ('max_size_bytes', models.BigIntegerField(blank=True, null=True)),
            ],
        ),
        migrations.CreateModel(
            name='BackupSchedule',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('name', models.CharField(max_length=128)),
                ('description', models.TextField(blank=True)),
                ('schedule_type', models.CharField(choices=[('daily', 'Daily'), ('weekly', 'Weekly'), ('monthly', 'Monthly'), ('custom_cron', 'Custom Cron')], default='daily', max_length=20)),
                ('hour', models.IntegerField(default=0, help_text='Hour (0-23)')),
                ('minute', models.IntegerField(default=0, help_text='Minute (0-59)')),
                ('day_of_week', models.CharField(default='0', help_text='Day of week for weekly schedules (0=Sunday, 1=Monday, etc.)', max_length=7)),
                ('day_of_month', models.IntegerField(default=1, help_text='Day of month for monthly schedules (1-31)')),
                ('cron_expression', models.CharField(blank=True, help_text='Custom cron expression (minute hour day month day_of_week)', max_length=255)),
                ('enabled', models.BooleanField(default=True)),
                ('created_at', models.DateTimeField(auto_now_add=True)),
                ('updated_at', models.DateTimeField(auto_now=True)),
            ],
            options={
                'ordering': ['-enabled', 'name'],
            },
        ),
    ]
