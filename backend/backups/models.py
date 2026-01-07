"""
Backup Record Models
Tracks all backup operations, their status, and location of backup artifacts.
"""

from django.db import models


class Backup(models.Model):
    """
    Backup Model: Records a single backup operation for a device
    
    Fields:
        - device (ForeignKey): The device that was backed up
        - location (ForeignKey): Where the backup was stored
        - timestamp (DateTimeField): When the backup was created
        - status (CharField): Backup result (success, failed, pending, etc.)
        - size_bytes (BigIntegerField): Size of backed up configuration in bytes
        - artifact_path (CharField): Path/identifier of backup artifact in storage location
        - is_text (BooleanField): Whether artifact is text (True) or binary (False)
    
    Methods:
        - __str__(): Returns formatted string with device ID and timestamp
    
    Usage:
        Each successful backup operation creates a Backup record. These records are
        used for:
        - Tracking backup history and success rates
        - Enforcing retention policies (age and count limits)
        - Displaying restore options to users
        - Audit and compliance reporting
    """
    device = models.ForeignKey('devices.Device', on_delete=models.CASCADE, help_text='Device that was backed up')
    location = models.ForeignKey('locations.BackupLocation', on_delete=models.SET_NULL, null=True, help_text='Where this backup is stored')
    timestamp = models.DateTimeField(auto_now_add=True, help_text='When this backup was created')
    status = models.CharField(max_length=32, default='success', help_text='Backup status: success, failed, pending, etc.')
    size_bytes = models.BigIntegerField(null=True, blank=True, help_text='Size of configuration backup in bytes')
    artifact_path = models.CharField(max_length=256, help_text='Path or identifier of backup in storage location')
    is_text = models.BooleanField(default=True, help_text='True if text artifact (configs), False if binary')
    
    def __str__(self):
        """Return formatted string with device ID and timestamp"""
        return f"{self.device_id} @ {self.timestamp}"
