
from django.db import models
from django.contrib.auth.models import User
from core.models import Label
class Permission(models.Model):
    code = models.CharField(max_length=128, unique=True)
    description = models.TextField(blank=True)
    def __str__(self): return self.code
class Role(models.Model):
    name = models.CharField(max_length=64, unique=True)
    permissions = models.ManyToManyField(Permission, blank=True)
    labels = models.ManyToManyField(Label, blank=True)
    def __str__(self): return self.name
class UserRole(models.Model):
    user = models.ForeignKey(User, on_delete=models.CASCADE)
    role = models.ForeignKey(Role, on_delete=models.CASCADE)
    class Meta:
        unique_together = ('user','role')
