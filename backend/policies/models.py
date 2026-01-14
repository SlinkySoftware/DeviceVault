"""
Backup Policy Models
Defines backup retention policies and scheduling for automated backup operations.
Integrates with Celery Beat for distributed task scheduling.
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


class RetentionPolicy(models.Model):
    """
    RetentionPolicy Model: Defines how long to keep backups and cleanup rules
    
    Fields:
        - name (CharField): Descriptive name (e.g., "Keep Last 30")
        - max_backups (IntegerField): Maximum number of backups to retain per device (optional)
        - max_days (IntegerField): Maximum age of backups in days (optional)
        - max_size_bytes (BigIntegerField): Maximum total size of backups before cleanup (optional)
    
    Methods:
        - __str__(): Returns the policy name
    
    Usage:
        Multiple retention policies can be created with different rules. Devices reference
        a retention policy to determine how old backups are cleaned up. At least one
        condition (max_backups, max_days, or max_size) should be specified.
    """
    name = models.CharField(max_length=128, help_text='Descriptive name for this retention policy')
    max_backups = models.IntegerField(null=True, blank=True, help_text='Keep only last N backups')
    max_days = models.IntegerField(null=True, blank=True, help_text='Delete backups older than N days')
    max_size_bytes = models.BigIntegerField(null=True, blank=True, help_text='Delete oldest backups when total size exceeds N bytes')
    
    def __str__(self):
        """Return the policy name for admin display"""
        return self.name


class BackupSchedule(models.Model):
    """
    BackupSchedule Model: Defines when backups should be executed using Celery Beat
    
    Fields:
        - name (CharField): Descriptive schedule name (e.g., "Nightly 2 AM")
        - description (TextField): Detailed explanation of schedule purpose
        - schedule_type (CharField): Type of schedule (daily, weekly, monthly, custom_cron)
        - hour (IntegerField): Hour in 24-hour format (0-23)
        - minute (IntegerField): Minute (0-59)
        - day_of_week (CharField): Day for weekly schedules (0=Sunday, 1=Monday, etc.)
        - day_of_month (IntegerField): Day for monthly schedules (1-31)
        - cron_expression (CharField): Custom cron expression for advanced scheduling
        - enabled (BooleanField): Whether this schedule is active (default: True)
        - created_at (DateTimeField): When this schedule was created
        - updated_at (DateTimeField): When this schedule was last modified
    
    Methods:
        - __str__(): Returns the schedule name
        - get_celery_schedule(): Generates Celery Beat compatible schedule configuration
    
    Schedule Types:
        - daily: Runs every day at specified hour:minute
        - weekly: Runs on specified day of week at specified hour:minute
        - monthly: Runs on specified day of month at specified hour:minute
        - custom_cron: Uses raw cron expression for complex schedules
    
    Usage:
        Schedules are configured through the admin interface and Celery Beat
        reads them from the database to queue backup tasks at the specified times.
        Only enabled schedules will trigger backups.
    """
    SCHEDULE_CHOICES = [
        ('daily', 'Daily'),
        ('weekly', 'Weekly'),
        ('monthly', 'Monthly'),
        ('custom_cron', 'Custom Cron'),
    ]
    
    name = models.CharField(max_length=128, help_text='Display name for this schedule')
    description = models.TextField(blank=True, help_text='Explanation of when and why this schedule runs')
    schedule_type = models.CharField(max_length=20, choices=SCHEDULE_CHOICES, default='daily', help_text='Type of recurrence pattern')
    hour = models.IntegerField(default=0, help_text='Hour (0-23) when backup should execute')
    minute = models.IntegerField(default=0, help_text='Minute (0-59) when backup should execute')
    day_of_week = models.CharField(max_length=7, default='0', help_text='For weekly schedules: 0=Sunday, 1=Monday, ..., 6=Saturday')
    day_of_month = models.IntegerField(default=1, help_text='For monthly schedules: day of month (1-31)')
    cron_expression = models.CharField(max_length=255, blank=True, help_text='For custom schedules: cron expression (minute hour day month day_of_week)')
    enabled = models.BooleanField(default=True, help_text='Enable/disable this schedule')
    last_run_at = models.DateTimeField(null=True, blank=True, help_text='Last time this schedule executed backups')
    next_run_at = models.DateTimeField(null=True, blank=True, help_text='Calculated next execution time (cached for frontend)')
    created_at = models.DateTimeField(auto_now_add=True, help_text='When this schedule was created')
    updated_at = models.DateTimeField(auto_now=True, help_text='When this schedule was last modified')
    
    class Meta:
        ordering = ['-enabled', 'name']
    
    def __str__(self):
        """Return the schedule name for admin display"""
        return self.name
    
    def get_celery_schedule(self):
        """
        Generate Celery Beat schedule configuration
        
        Returns:
            dict: Celery Beat compatible schedule dictionary with timing parameters
            
        Examples:
            - Daily at 2:00 AM: {'minute': 0, 'hour': 2}
            - Weekly Friday at 3:30 AM: {'minute': 30, 'hour': 3, 'day_of_week': 5}
            - Monthly 1st at 4:00 AM: {'minute': 0, 'hour': 4, 'day_of_month': 1}
        """
        if self.schedule_type == 'daily':
            return {'minute': self.minute, 'hour': self.hour}
        elif self.schedule_type == 'weekly':
            return {'minute': self.minute, 'hour': self.hour, 'day_of_week': self.day_of_week}
        elif self.schedule_type == 'monthly':
            return {'minute': self.minute, 'hour': self.hour, 'day_of_month': self.day_of_month}
        elif self.schedule_type == 'custom_cron':
            return {'crontab': self.cron_expression}
        # Default to daily if type not recognized
        return {'minute': self.minute, 'hour': self.hour}
