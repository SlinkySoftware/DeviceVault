"""
Device Management Models
Defines core device data structures for the DeviceVault backup system.
Includes device types, manufacturers, and device inventory management.
"""

from django.db import models
from core.models import Label


class DeviceType(models.Model):
    """
    DeviceType Model: Represents the category/type of network device
    
    Fields:
        - name (CharField): Unique name identifying the device type (e.g., Router, Switch)
        - icon (CharField): Material Design icon name for UI display (e.g., router, wifi, security)
    
    Methods:
        - __str__(): Returns the device type name
    """
    name = models.CharField(max_length=64, unique=True)
    icon = models.CharField(max_length=64, default='router', blank=True, help_text='Material Design icon name')
    
    def __str__(self):
        """Return the device type name for admin display"""
        return self.name


class Manufacturer(models.Model):
    """
    Manufacturer Model: Represents the hardware manufacturer of devices
    
    Fields:
        - name (CharField): Unique name of the manufacturer (e.g., Cisco, Fortinet)
    
    Methods:
        - __str__(): Returns the manufacturer name
    """
    name = models.CharField(max_length=64, unique=True)
    
    def __str__(self):
        """Return the manufacturer name for admin display"""
        return self.name


class Device(models.Model):
    """
    Device Model: Represents a network device to be managed and backed up
    
    Fields:
        - name (CharField): Unique identifier/hostname of the device
        - ip_address (GenericIPAddressField): IPv4 address for SSH/telnet connection
        - dns_name (CharField): FQDN for device resolution (optional)
        - device_type (ForeignKey): Type of device (Router, Switch, Firewall, etc.)
        - manufacturer (ForeignKey): Hardware manufacturer
        - labels (ManyToManyField): Tags for organization and filtering (Production, DMZ, etc.)
        - enabled (BooleanField): Whether device is active for backups (default: True)
        - is_example_data (BooleanField): If True, device is excluded from backup processing (default: False)
        - last_backup_time (DateTimeField): Timestamp of most recent successful backup
        - last_backup_status (CharField): Status of last backup attempt (success/failed/pending)
        - retention_policy (ForeignKey): Backup retention rules to apply to this device
        - backup_location (ForeignKey): Where backups are stored (Git repo, S3, filesystem, etc.)
        - credential (ForeignKey): Authentication details for device access
    
    Methods:
        - __str__(): Returns the device name for admin display
    
    Usage:
        Devices are created through the Django admin or API, typically linked to a backup schedule
        and backup location. The is_example_data flag allows marking demo devices to exclude them
        from production backup operations.
    """
    name = models.CharField(max_length=128, help_text='Device hostname or identifier')
    ip_address = models.GenericIPAddressField(protocol='IPv4', help_text='IPv4 address for SSH/Telnet connection')
    dns_name = models.CharField(max_length=128, blank=True, help_text='FQDN for DNS resolution (optional)')
    device_type = models.ForeignKey(DeviceType, on_delete=models.PROTECT, help_text='Type of device (Router, Switch, etc.)')
    manufacturer = models.ForeignKey(Manufacturer, on_delete=models.PROTECT, help_text='Hardware manufacturer')
    labels = models.ManyToManyField(Label, blank=True, help_text='Tags for organization (Production, DMZ, etc.)')
    enabled = models.BooleanField(default=True, help_text='Enable/disable this device for backups')
    is_example_data = models.BooleanField(default=False, help_text='Mark as example/demo data to exclude from backups')
    last_backup_time = models.DateTimeField(null=True, blank=True, help_text='Timestamp of last successful backup')
    last_backup_status = models.CharField(max_length=32, blank=True, help_text='Status of last backup: success, failed, pending, etc.')
    retention_policy = models.ForeignKey('policies.RetentionPolicy', on_delete=models.SET_NULL, null=True, blank=True, help_text='Backup retention policy')
    backup_location = models.ForeignKey('locations.BackupLocation', on_delete=models.SET_NULL, null=True, blank=True, help_text='Where to store backups')
    credential = models.ForeignKey('credentials.Credential', on_delete=models.SET_NULL, null=True, blank=True, help_text='SSH/Telnet credentials for device access')
    
    def __str__(self):
        """Return device name for admin display"""
        return self.name
