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
    timestamp = models.DateTimeField(auto_now_add=True, help_text='When this backup record was created')
    requested_at = models.DateTimeField(null=True, blank=True, help_text='When this backup was requested')
    started_at = models.DateTimeField(null=True, blank=True, help_text='When backup execution started')
    completed_at = models.DateTimeField(null=True, blank=True, help_text='When backup execution completed')
    status = models.CharField(max_length=32, default='pending', help_text='Backup status: pending, in_progress, success, failed')
    size_bytes = models.BigIntegerField(null=True, blank=True, help_text='Size of configuration backup in bytes')
    artifact_path = models.CharField(max_length=256, help_text='Path or identifier of backup in storage location')
    is_text = models.BooleanField(default=True, help_text='True if text artifact (configs), False if binary')
    
    @property
    def duration_seconds(self):
        """Return duration in seconds if start and completion timestamps are available."""
        if self.started_at and self.completed_at:
            return int((self.completed_at - self.started_at).total_seconds())
        return None

    def __str__(self):
        """Return formatted string with device ID and timestamp"""
        return f"{self.device_id} @ {self.timestamp}"
