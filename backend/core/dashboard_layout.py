from django.db import models
from django.contrib.auth.models import User
import json


class DashboardLayout(models.Model):
    """Store dashboard widget configuration per user or as default"""
    user = models.OneToOneField(User, on_delete=models.CASCADE, related_name='dashboard_layout', null=True, blank=True)
    is_default = models.BooleanField(default=False)
    
    # JSON structure: [{ x, y, w, h, i (widget_id) }, ...]
    layout = models.JSONField(default=list)
    
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    
    class Meta:
        unique_together = [['user', 'is_default']]
    
    def __str__(self):
        if self.is_default:
            return f"Default Dashboard Layout"
        return f"Dashboard Layout for {self.user.username}"
