"""
Device Management Models
Defines core device data structures for the DeviceVault backup system.
Includes device types, manufacturers, device inventory management, and device groups (the unit of access control).
"""

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
from django.db.models.signals import pre_delete
from django.dispatch import receiver

# ===== Collection Group Models =====


class CollectionGroup(models.Model):
    """
    CollectionGroup Model: Groups devices for collection task assignment

    Fields:
        - name (CharField): Unique collection group name
        - description (TextField): Description of the collection group's purpose
        - rabbitmq_queue_id (CharField): RabbitMQ queue ID for task distribution
        - created_at (DateTimeField): When group was created
        - updated_at (DateTimeField): When group was last modified

    Methods:
        - __str__(): Returns the collection group name
        - device_count: Property that returns count of devices in this group

    Usage:
        Collection groups are used to assign data collection tasks to specific
        worker processes. Devices are assigned to collection groups, and workers
        listening on the group's RabbitMQ queue will receive collection tasks.
    """

    name = models.CharField(max_length=128, unique=True, help_text='Unique collection group name')
    description = models.TextField(blank=True, help_text='Description of the collection group purpose')
    rabbitmq_queue_id = models.CharField(max_length=128, help_text='RabbitMQ queue ID for task distribution')
    created_at = models.DateTimeField(auto_now_add=True, help_text='When group was created')
    updated_at = models.DateTimeField(auto_now=True, help_text='When group was last modified')

    def __str__(self):
        """Return collection group name for admin display"""
        return self.name

    @property
    def device_count(self):
        """Return count of devices assigned to this collection group"""
        return self.devices.count()

    def save(self, *args, **kwargs):
        # Ensure name is clean and not padded with whitespace
        if self.name is not None:
            self.name = self.name.strip()
        if self.rabbitmq_queue_id is not None:
            self.rabbitmq_queue_id = self.rabbitmq_queue_id.strip()
        super().save(*args, **kwargs)

    class Meta:
        verbose_name = 'Collection Group'
        verbose_name_plural = 'Collection Groups'
        ordering = ['name']


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
    """A network device to back up.

    ``backup_method`` names a collector driver offered by approved collectors;
    ``driver_params`` holds that driver's per-device settings (validated against
    the schema it advertises). Backups run on ``schedule`` or on demand, on the
    collectors of ``collection_group``, and are written to ``backup_location``.
    ``last_backup_time``/``last_backup_status`` reflect the latest finished job.
    """

    name = models.CharField(max_length=128, help_text='Device hostname or identifier')
    ip_address = models.GenericIPAddressField(help_text='IPv4 or IPv6 address the collector connects to')
    dns_name = models.CharField(max_length=128, blank=True, help_text='FQDN for DNS resolution (optional)')
    device_type = models.ForeignKey(
        DeviceType, on_delete=models.PROTECT, help_text='Type of device (Router, Switch, etc.)'
    )
    manufacturer = models.ForeignKey(
        Manufacturer, on_delete=models.PROTECT, null=True, blank=True, help_text='Hardware manufacturer (optional)'
    )
    backup_method = models.CharField(max_length=128, default='noop', help_text='Collector driver key')
    driver_params = models.JSONField(default=dict, blank=True, help_text='Per-device settings for the driver')
    device_group = models.ForeignKey(
        'DeviceGroup',
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        help_text='Device group (controls who has access)',
    )
    collection_group = models.ForeignKey(
        'CollectionGroup',
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='devices',
        help_text='Collection group for task distribution',
    )
    schedule = models.ForeignKey(
        'policies.BackupSchedule',
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='devices',
        help_text='When to back up automatically (none: on demand only)',
    )
    enabled = models.BooleanField(default=True, help_text='Enable/disable this device for backups')
    last_backup_time = models.DateTimeField(null=True, blank=True, help_text='When the latest backup job finished')
    last_backup_status = models.CharField(max_length=32, blank=True, help_text='success or failure')
    retention_policy = models.ForeignKey(
        'policies.RetentionPolicy',
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        help_text='Backup retention policy',
    )
    storage_target = models.ForeignKey(
        'storage.StorageTarget',
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='devices',
        help_text='Where backups are stored',
    )
    credential = models.ForeignKey(
        'credentials.Credential',
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        help_text='SSH/Telnet credentials for device access',
    )

    def __str__(self):
        return self.name


# ===== Device groups =====


class DeviceGroup(models.Model):
    """A set of devices, and the unit of access control.

    User groups are granted permissions on device groups (accounts.DeviceGroupGrant).
    A device belongs to at most one group; ungrouped devices are for global
    administrators only.
    """

    name = models.CharField(max_length=128, unique=True, help_text='Unique device group name')
    description = models.TextField(blank=True, help_text='Description of the device group purpose')
    created_at = models.DateTimeField(auto_now_add=True, help_text='When group was created')
    updated_at = models.DateTimeField(auto_now=True, help_text='When group was last modified')

    class Meta:
        ordering = ['name']

    def __str__(self):
        """Return device group name for admin display"""
        return self.name

    def save(self, *args, **kwargs):
        # Ensure name is clean and not padded with whitespace
        if self.name is not None:
            self.name = self.name.strip()
        super().save(*args, **kwargs)


@receiver(pre_delete, sender=CollectionGroup)
def prevent_delete_if_devices_in_collection_group(sender, instance, **kwargs):
    """Block deletion of collection groups if any devices are assigned to them"""
    if instance.device_count > 0:
        from django.core.exceptions import ValidationError

        raise ValidationError(
            f'Cannot delete collection group "{instance.name}": {instance.device_count} device(s) are assigned to this group.'
        )
