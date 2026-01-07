"""
Core Application Models
Defines user preferences and dashboard layout configuration.
"""

from django.db import models
from django.contrib.auth.models import User


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

