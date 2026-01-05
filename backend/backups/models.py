
from django.db import models
class Backup(models.Model):
    device = models.ForeignKey('devices.Device', on_delete=models.CASCADE)
    location = models.ForeignKey('locations.BackupLocation', on_delete=models.SET_NULL, null=True)
    timestamp = models.DateTimeField(auto_now_add=True)
    status = models.CharField(max_length=32, default='success')
    size_bytes = models.BigIntegerField(null=True, blank=True)
    artifact_path = models.CharField(max_length=256)
    is_text = models.BooleanField(default=True)
    def __str__(self): return f"{self.device_id} @ {self.timestamp}"
