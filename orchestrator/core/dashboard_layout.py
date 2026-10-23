"""
DeviceVault - A comprehensive network device backup management application with web interface for user and admin access and backend component for automated backup collection.
Copyright (C) 2026, Slinky Software

This program is free software: you can redistribute it and/or modify
it under the terms of the GNU General Public License as published by
the Free Software Foundation, either version 3 of the License, or
 (at your option) any later version.

This program is distributed in the hope that it will be useful,
but WITHOUT ANY WARRANTY; without even the implied warranty of
MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
GNU General Public License for more details.

You should have received a copy of the GNU General Public License
along with this program.  If not, see <http://www.gnu.org/licenses/>.
"""

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
