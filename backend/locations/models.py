"""
Backup Location Models
Defines where device configuration backups are stored (Git repositories, S3, filesystem, TFTP, etc.).
"""

from django.db import models


class BackupLocation(models.Model):
    """
    BackupLocation Model: Defines a storage destination for device configuration backups
    
    Fields:
        - name (CharField): Display name for location (e.g., "Primary Git Repo")
        - location_type (CharField): Type of location (git, s3, filesystem, tftp, etc.)
        - config (JSONField): Location-specific configuration parameters
    
    Methods:
        - __str__(): Returns formatted string with type and name
    
    Location Types and Config Examples:
        - git: {url, branch, username, password}
        - s3: {bucket, region, access_key, secret_key}
        - filesystem: {path}
        - tftp: {host, port}
    
    Usage:
        Devices reference a backup location to specify where their configurations
        are saved. Multiple locations allow backup redundancy and distribution.
    """
    name = models.CharField(max_length=128, help_text='Display name for this backup location')
    location_type = models.CharField(max_length=64, help_text='Type of location: git, s3, filesystem, tftp, etc.')
    config = models.JSONField(default=dict, help_text='Location-specific configuration (URL, credentials, path, etc.)')
    
    def __str__(self):
        """Return formatted string with location type and name"""
        return f"{self.location_type}:{self.name}"
