
from django.db import models
class BackupLocation(models.Model):
    name = models.CharField(max_length=128)
    location_type = models.CharField(max_length=64)
    config = models.JSONField(default=dict)
    def __str__(self): return f"{self.location_type}:{self.name}"
