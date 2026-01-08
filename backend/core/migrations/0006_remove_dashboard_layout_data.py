from django.db import migrations


def delete_dashboard_layouts(apps, schema_editor):
    DashboardLayout = apps.get_model('core', 'DashboardLayout')
    DashboardLayout.objects.all().delete()


def noop(apps, schema_editor):
    pass


class Migration(migrations.Migration):

    dependencies = [
        ('core', '0005_delete_label'),
    ]

    operations = [
        migrations.RunPython(delete_dashboard_layouts, reverse_code=noop),
    ]
