
from django.db import models
class Label(models.Model):
    name = models.CharField(max_length=64, unique=True)
    description = models.TextField(blank=True)
    def __str__(self): return self.name
