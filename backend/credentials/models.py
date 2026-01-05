
from django.db import models
class CredentialType(models.Model):
    name = models.CharField(max_length=64, unique=True)
    def __str__(self): return self.name
class Credential(models.Model):
    name = models.CharField(max_length=128)
    credential_type = models.ForeignKey(CredentialType, on_delete=models.PROTECT)
    data = models.JSONField(default=dict)
    def __str__(self): return self.name
