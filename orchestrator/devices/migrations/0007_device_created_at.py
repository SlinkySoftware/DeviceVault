import django.utils.timezone
from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ('devices', '0006_generated_queue_ids'),
    ]

    operations = [
        migrations.AddField(
            model_name='device',
            name='created_at',
            field=models.DateTimeField(
                auto_now_add=True, default=django.utils.timezone.now, help_text='When the device was added'
            ),
            preserve_default=False,
        ),
    ]
