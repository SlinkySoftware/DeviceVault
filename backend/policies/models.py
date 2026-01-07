
from django.db import models

class RetentionPolicy(models.Model):
    name = models.CharField(max_length=128)
    max_backups = models.IntegerField(null=True, blank=True)
    max_days = models.IntegerField(null=True, blank=True)
    max_size_bytes = models.BigIntegerField(null=True, blank=True)
    def __str__(self): return self.name

class BackupSchedule(models.Model):
    SCHEDULE_CHOICES = [
        ('daily', 'Daily'),
        ('weekly', 'Weekly'),
        ('monthly', 'Monthly'),
        ('custom_cron', 'Custom Cron'),
    ]
    
    name = models.CharField(max_length=128)
    description = models.TextField(blank=True)
    schedule_type = models.CharField(max_length=20, choices=SCHEDULE_CHOICES, default='daily')
    hour = models.IntegerField(default=0, help_text='Hour (0-23)')
    minute = models.IntegerField(default=0, help_text='Minute (0-59)')
    day_of_week = models.CharField(max_length=7, default='0', help_text='Day of week for weekly schedules (0=Sunday, 1=Monday, etc.)')
    day_of_month = models.IntegerField(default=1, help_text='Day of month for monthly schedules (1-31)')
    cron_expression = models.CharField(max_length=255, blank=True, help_text='Custom cron expression (minute hour day month day_of_week)')
    enabled = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    
    class Meta:
        ordering = ['-enabled', 'name']
    
    def __str__(self): return self.name
    
    def get_celery_schedule(self):
        """Generate Celery Beat schedule configuration"""
        if self.schedule_type == 'daily':
            return {'minute': self.minute, 'hour': self.hour}
        elif self.schedule_type == 'weekly':
            return {'minute': self.minute, 'hour': self.hour, 'day_of_week': self.day_of_week}
        elif self.schedule_type == 'monthly':
            return {'minute': self.minute, 'hour': self.hour, 'day_of_month': self.day_of_month}
        elif self.schedule_type == 'custom_cron':
            return {'crontab': self.cron_expression}
        return {'minute': self.minute, 'hour': self.hour}
