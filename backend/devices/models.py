
from django.db import models
from core.models import Label
class DeviceType(models.Model):
    name = models.CharField(max_length=64, unique=True)
    icon = models.CharField(max_length=64, default='router', blank=True)
    def __str__(self): return self.name
class Manufacturer(models.Model):
    name = models.CharField(max_length=64, unique=True)
    def __str__(self): return self.name
class Device(models.Model):
    name = models.CharField(max_length=128)
    ip_address = models.GenericIPAddressField(protocol='IPv4')
    dns_name = models.CharField(max_length=128, blank=True)
    device_type = models.ForeignKey(DeviceType, on_delete=models.PROTECT)
    manufacturer = models.ForeignKey(Manufacturer, on_delete=models.PROTECT)
    labels = models.ManyToManyField(Label, blank=True)
    enabled = models.BooleanField(default=True)
    is_example_data = models.BooleanField(default=False, help_text='Mark as example data to exclude from backup processing')
    last_backup_time = models.DateTimeField(null=True, blank=True)
    last_backup_status = models.CharField(max_length=32, blank=True)
    retention_policy = models.ForeignKey('policies.RetentionPolicy', on_delete=models.SET_NULL, null=True, blank=True)
    backup_location = models.ForeignKey('locations.BackupLocation', on_delete=models.SET_NULL, null=True, blank=True)
    credential = models.ForeignKey('credentials.Credential', on_delete=models.SET_NULL, null=True, blank=True)
    def __str__(self): return self.name
