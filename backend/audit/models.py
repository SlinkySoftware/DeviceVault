
from django.db import models
from django.contrib.auth.models import User
class AuditLog(models.Model):
    created_at = models.DateTimeField(auto_now_add=True)
    actor = models.ForeignKey(User, on_delete=models.SET_NULL, null=True)
    action = models.CharField(max_length=128)
    resource = models.CharField(max_length=128)
    details = models.JSONField(default=dict)
    label_scope = models.JSONField(default=list)
