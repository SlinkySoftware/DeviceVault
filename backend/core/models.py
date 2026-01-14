"""
Core Application Models
Defines user preferences and dashboard layout configuration.
"""

# DeviceVault - A comprehensive network device backup management application with web interface for user and admin access and backend component for automated backup collection.
# Copyright (C) 2026, Slinky Software
#
# This program is free software: you can redistribute it and/or modify
# it under the terms of the GNU General Public License as published by
# the Free Software Foundation, either version 3 of the License, or
# (at your option) any later version.
#
# This program is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
# GNU General Public License for more details.
#
# You should have received a copy of the GNU General Public License
# along with this program.  If not, see <http://www.gnu.org/licenses/>.

from django.db import models
from django.contrib.auth.models import User
from django.core.cache import cache
from .theme_settings import ThemeSettings


# Label model removed - Device Groups replaced the label-based organization system


class UserProfile(models.Model):
    """
    UserProfile Model: Stores user-specific preferences and settings
    
    Fields:
        - user (OneToOneField): Link to Django User account
        - theme (CharField): UI theme preference (light or dark)
        - created_at (DateTimeField): When profile was created
        - updated_at (DateTimeField): When profile was last modified
    
    Methods:
        - __str__(): Returns descriptive string with username
    
    Theme Options:
        - light: Light mode UI
        - dark: Dark mode UI (default)
    
    Usage:
        Each user has one associated profile containing their preferences.
        Profile is created automatically when user logs in if it doesn't exist.
    """
    THEME_CHOICES = [
        ('light', 'Light Mode'),
        ('dark', 'Dark Mode'),
    ]
    
    user = models.OneToOneField(User, on_delete=models.CASCADE, related_name='profile', help_text='Associated user account')
    theme = models.CharField(max_length=10, choices=THEME_CHOICES, default='dark', help_text='UI theme preference')
    created_at = models.DateTimeField(auto_now_add=True, help_text='Profile creation timestamp')
    updated_at = models.DateTimeField(auto_now=True, help_text='Last modification timestamp')
    
    def __str__(self):
        """Return profile description with username"""
        return f"Profile for {self.user.username}"


class DashboardLayout(models.Model):
    """
    DashboardLayout Model: Stores dashboard widget configuration per user or as default
    
    Fields:
        - user (OneToOneField): User who owns this layout (null for default layout)
        - is_default (BooleanField): Whether this is the default layout for new users
        - layout (JSONField): Array of widget configuration objects
        - created_at (DateTimeField): When layout was created
        - updated_at (DateTimeField): When layout was last modified
    
    Methods:
        - __str__(): Returns descriptive string
    
    Layout Structure:
        layout is a JSON array of widget objects, each containing:
        - type: Widget type (stats, chart, table, etc.)
        - position: Grid position {row, col}
        - size: Widget dimensions {width, height}
        - config: Widget-specific configuration
    
    Usage:
        Each user can customize their dashboard layout.
        A default layout is provided for new users and can be customized by admins.
        Users can have only one layout, and either it's personal or the default.
    """
    user = models.OneToOneField(User, on_delete=models.CASCADE, related_name='dashboard_layout', null=True, blank=True, help_text='User who customized this layout (null for default)')
    is_default = models.BooleanField(default=False, help_text='Whether this is the default layout for all users')
    layout = models.JSONField(default=list, help_text='Dashboard widget configuration as JSON array')
    created_at = models.DateTimeField(auto_now_add=True, help_text='Layout creation timestamp')
    updated_at = models.DateTimeField(auto_now=True, help_text='Last modification timestamp')
    
    class Meta:
        unique_together = [['user', 'is_default']]
    
    def __str__(self):
        """Return descriptive string with user or default indicator"""
        if self.is_default:
            return "Default Dashboard Layout"
        return f"Dashboard Layout for {self.user.username}"


class SchedulerState(models.Model):
    """
    SchedulerState Model: Singleton storing scheduler execution state
    
    Fields:
        - last_tick (DateTimeField): Last time scheduler checked for scheduled backups
        - is_running (BooleanField): Whether scheduler is currently active
        - scheduler_pid (IntegerField): Process ID of running scheduler
        - last_restart_at (DateTimeField): Last time scheduler was restarted
        - updated_at (DateTimeField): Last update timestamp
    
    Only one instance exists (pk=1 singleton pattern).
    Used to track scheduler state and detect missed backup windows on restart.
    """
    last_tick = models.DateTimeField(null=True, blank=True, help_text='Last time scheduler processed schedules')
    is_running = models.BooleanField(default=False, help_text='Whether scheduler is currently running')
    scheduler_pid = models.IntegerField(null=True, blank=True, help_text='Process ID of running scheduler')
    last_restart_at = models.DateTimeField(null=True, blank=True, help_text='Last scheduler restart timestamp')
    updated_at = models.DateTimeField(auto_now=True)
    
    class Meta:
        verbose_name = 'Scheduler State'
        verbose_name_plural = 'Scheduler State'
    
    def __str__(self):
        return 'Scheduler State'
    
    def save(self, *args, **kwargs):
        """Override save to ensure only one instance exists and clear cache"""
        self.pk = 1
        super().save(*args, **kwargs)
        cache.delete('scheduler_state')
    
    @classmethod
    def load(cls):
        """Load scheduler state from database or cache"""
        cached = cache.get('scheduler_state')
        if cached:
            return cached
        
        obj, created = cls.objects.get_or_create(pk=1)
        cache.set('scheduler_state', obj, timeout=300)  # Cache for 5 minutes
        return obj

