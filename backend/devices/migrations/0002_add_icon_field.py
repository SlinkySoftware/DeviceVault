# Generated migration to add icon field to DeviceType

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('devices', '0001_initial'),
    ]

    operations = [
        migrations.AddField(
            model_name='devicetype',
            name='icon',
            field=models.CharField(blank=True, default='router', max_length=64),
        ),
    ]
