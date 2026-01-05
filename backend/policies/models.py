
from django.db import models
class RetentionPolicy(models.Model):
    name = models.CharField(max_length=128)
    max_backups = models.IntegerField(null=True, blank=True)
    max_days = models.IntegerField(null=True, blank=True)
    max_size_bytes = models.BigIntegerField(null=True, blank=True)
    def __str__(self): return self.name
