"""
Theme Settings Management
Provides storage and retrieval of application theme configuration
"""

from django.db import models
from django.core.cache import cache


class ThemeSettings(models.Model):
    """
    ThemeSettings Model: Stores application-wide theme configuration
    
    Fields:
        - title_bar_color (CharField): Color for application title bar/header
        - dashboard_box_color (CharField): Color for dashboard widget boxes
        - dashboard_nested_box_color (CharField): Color for nested boxes within dashboard widgets
        - updated_at (DateTimeField): Last update timestamp
    
    Only one instance should exist (singleton pattern).
    Settings are cached for performance.
    """
    title_bar_color = models.CharField(
        max_length=7, 
        default='#1976D2',
        help_text='Hex color code for application title bar (e.g., #1976D2)'
    )
    dashboard_box_color = models.CharField(
        max_length=7, 
        default='#1976D2',
        help_text='Hex color code for dashboard boxes (e.g., #1976D2)'
    )
    dashboard_nested_box_color = models.CharField(
        max_length=7, 
        default='#2196F3',
        help_text='Hex color code for dashboard nested boxes (e.g., #2196F3)'
    )
    updated_at = models.DateTimeField(auto_now=True)
    
    class Meta:
        verbose_name = 'Theme Settings'
        verbose_name_plural = 'Theme Settings'
    
    def __str__(self):
        return 'Theme Settings'
    
    def save(self, *args, **kwargs):
        """Override save to ensure only one instance exists and clear cache"""
        self.pk = 1
        super().save(*args, **kwargs)
        # Clear cache when settings are updated
        cache.delete('theme_settings')
    
    @classmethod
    def load(cls):
        """Load theme settings from database or cache"""
        cached = cache.get('theme_settings')
        if cached:
            return cached
        
        obj, created = cls.objects.get_or_create(pk=1)
        cache.set('theme_settings', obj, timeout=3600)  # Cache for 1 hour
        return obj
