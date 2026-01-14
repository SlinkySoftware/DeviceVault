"""
Device Management Models
Defines core device data structures for the DeviceVault backup system.
Includes device types, manufacturers, device inventory management, and device groups for RBAC.
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
from django.utils import timezone
from django.contrib.auth.models import User, Group as AuthGroup, Permission as AuthPermission
from django.contrib.contenttypes.models import ContentType
from django.db.models.signals import post_save, pre_delete
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
    """
    Device Model: Represents a network device to be managed and backed up
    
    Fields:
        - name (CharField): Unique identifier/hostname of the device
        - ip_address (GenericIPAddressField): IPv4 address for SSH/telnet connection
        - dns_name (CharField): FQDN for device resolution (optional)
        - device_type (ForeignKey): Type of device (Router, Switch, Firewall, etc.)
        - manufacturer (ForeignKey): Hardware manufacturer (optional)
        - backup_method (CharField): Backup plugin key to use (e.g. mikrotik_ssh_export, noop, etc.)
        - device_group (ForeignKey): Device group for RBAC access control
        - enabled (BooleanField): Whether device is active for backups (default: True)
        - last_backup_time (DateTimeField): Timestamp of most recent successful backup
        - last_backup_status (CharField): Status of last backup attempt (success/failed/pending)
        - retention_policy (ForeignKey): Backup retention rules to apply to this device
        - backup_location (ForeignKey): Where backups are stored (Git repo, S3, filesystem, etc.)
        - credential (ForeignKey): Authentication details for device access
    
    Methods:
        - __str__(): Returns the device name for admin display
    
    Usage:
        Devices are created through the Django admin or API, linked to a device group for RBAC.
        Access to devices is controlled via device group roles and permissions.
    """
    name = models.CharField(max_length=128, help_text='Device hostname or identifier')
    ip_address = models.GenericIPAddressField(protocol='IPv4', help_text='IPv4 address for SSH/Telnet connection')
    dns_name = models.CharField(max_length=128, blank=True, help_text='FQDN for DNS resolution (optional)')
    device_type = models.ForeignKey(DeviceType, on_delete=models.PROTECT, help_text='Type of device (Router, Switch, etc.)')
    manufacturer = models.ForeignKey(Manufacturer, on_delete=models.PROTECT, null=True, blank=True, help_text='Hardware manufacturer (optional)')
    backup_method = models.CharField(max_length=128, default='noop', help_text='Backup plugin key to use for this device')
    device_group = models.ForeignKey('DeviceGroup', on_delete=models.PROTECT, null=True, blank=True, help_text='Device group for RBAC access control')
    collection_group = models.ForeignKey('CollectionGroup', on_delete=models.SET_NULL, null=True, blank=True, related_name='devices', help_text='Collection group for task distribution')
    enabled = models.BooleanField(default=True, help_text='Enable/disable this device for backups')
    last_backup_time = models.DateTimeField(null=True, blank=True, help_text='Timestamp of last successful backup')
    last_backup_status = models.CharField(max_length=32, blank=True, help_text='Status of last backup: success, failed, pending, etc.')
    retention_policy = models.ForeignKey('policies.RetentionPolicy', on_delete=models.SET_NULL, null=True, blank=True, help_text='Backup retention policy')
    backup_schedule = models.ForeignKey('policies.BackupSchedule', on_delete=models.SET_NULL, null=True, blank=True, help_text='Automated backup schedule')
    backup_location = models.ForeignKey('locations.BackupLocation', on_delete=models.SET_NULL, null=True, blank=True, help_text='Where to store backups')
    credential = models.ForeignKey('credentials.Credential', on_delete=models.SET_NULL, null=True, blank=True, help_text='SSH/Telnet credentials for device access')
    
    def __str__(self):
        """Return device name for admin display"""
        return self.name


class DeviceBackupResult(models.Model):
    """
    Stores the result metadata for a device backup collection task.

    Note: The raw device configuration is NOT stored here; this model stores
    references / tracing information. The `task_identifier` is intended to be
    a logical identifier for the backup job so storage backends can retrieve
    the actual device_config artifact if necessary.
    """
    task_id = models.CharField(max_length=64, db_index=True)
    task_identifier = models.CharField(max_length=128, db_index=True)
    device = models.ForeignKey('Device', on_delete=models.CASCADE, db_index=True)
    status = models.CharField(max_length=16)
    timestamp = models.DateTimeField()
    log = models.TextField(help_text='JSON serialized list of log messages')
    
    # Timing metrics (in milliseconds)
    initiated_at = models.DateTimeField(null=True, blank=True, help_text='UTC timestamp when backup was initiated (step 1)')
    collection_duration_ms = models.IntegerField(null=True, blank=True, help_text='Collection execution time in milliseconds (step 3)')
    overall_duration_ms = models.IntegerField(null=True, blank=True, help_text='Overall processing time from initiation to completion in milliseconds')

    class Meta:
        ordering = ['-timestamp']

    def __str__(self):
        return f"{self.task_identifier} @ {self.device.name} -> {self.status}"


# ===== Device Group RBAC Models =====

class DeviceGroup(models.Model):
    """
    DeviceGroup Model: Organizes devices into logical groups for RBAC
    
    Fields:
        - name (CharField): Unique device group name (e.g., "Production Routers", "DMZ Firewalls")
        - description (TextField): Optional description of the group's purpose
        - created_at (DateTimeField): When group was created
        - updated_at (DateTimeField): When group was last modified
    
    Methods:
        - __str__(): Returns the device group name
    
    Usage:
        Device groups replace local labels/tags for organizing devices.
        Each device is assigned to exactly one device group.
        Roles are granted permissions to device groups (view, edit, add device, delete device, etc.)
        Users/groups with these roles can perform the allowed actions on devices in that group.
    """
    name = models.CharField(max_length=128, unique=True, help_text='Unique device group name')
    description = models.TextField(blank=True, help_text='Description of the device group purpose')
    created_at = models.DateTimeField(auto_now_add=True, help_text='When group was created')
    updated_at = models.DateTimeField(auto_now=True, help_text='When group was last modified')
    
    def __str__(self):
        """Return device group name for admin display"""
        return self.name

    def save(self, *args, **kwargs):
        # Ensure name is clean and not padded with whitespace
        if self.name is not None:
            self.name = self.name.strip()
        super().save(*args, **kwargs)


class DeviceGroupDjangoPermissions(models.Model):
    """
    Maps a DeviceGroup to its corresponding Django auth Permissions.
    Creates four permissions per device group:
    - Device Group - {name} - Can View
    - Device Group - {name} - Can Modify
    - Device Group - {name} - Can View Backups
    - Device Group - {name} - Can Backup Now
    """
    device_group = models.OneToOneField(DeviceGroup, on_delete=models.CASCADE, related_name='django_permissions')
    perm_view = models.ForeignKey(
        AuthPermission,
        on_delete=models.CASCADE,
        related_name='dg_perm_view',
        null=True,
        blank=True,
        default=None,
    )
    perm_modify = models.ForeignKey(
        AuthPermission,
        on_delete=models.CASCADE,
        related_name='dg_perm_modify',
        null=True,
        blank=True,
        default=None,
    )
    perm_view_backups = models.ForeignKey(
        AuthPermission,
        on_delete=models.CASCADE,
        related_name='dg_perm_view_backups',
        null=True,
        blank=True,
        default=None,
    )
    perm_backup_now = models.ForeignKey(
        AuthPermission,
        on_delete=models.CASCADE,
        related_name='dg_perm_backup_now',
        null=True,
        blank=True,
        default=None,
    )

    def __str__(self):
        return f"RBAC|DG_{self.device_group.name}"

    @staticmethod
    def slugify_name(group_name: str) -> str:
        import re
        slug = group_name.strip().lower()
        slug = re.sub(r"[^a-z0-9]+", "_", slug)
        slug = re.sub(r"_+", "_", slug).strip('_')
        return slug or "group"

    @classmethod
    def ensure_for_group(cls, device_group):
        slug = cls.slugify_name(device_group.name)
        ct = ContentType.objects.get_for_model(DeviceGroup)
        perms = {}
        
        permission_specs = [
            ('view', f'Device Group - {device_group.name} - Can View'),
            ('modify', f'Device Group - {device_group.name} - Can Modify'),
            ('view_backups', f'Device Group - {device_group.name} - Can View Backups'),
            ('backup_now', f'Device Group - {device_group.name} - Can Backup Now'),
        ]
        
        for action, name in permission_specs:
            codename = f"dg_{slug}_{action}"
            perm, _ = AuthPermission.objects.get_or_create(codename=codename, content_type=ct, defaults={"name": name})
            # If name drifted, refresh it to reflect current group name
            if perm.name != name:
                perm.name = name
                perm.save(update_fields=["name"])
            perms[action] = perm
        
        instance, _ = cls.objects.get_or_create(
            device_group=device_group,
            defaults={
                'perm_view': perms['view'],
                'perm_modify': perms['modify'],
                'perm_view_backups': perms['view_backups'],
                'perm_backup_now': perms['backup_now'],
            }
        )
        updated = False
        if instance.perm_view_id != perms['view'].id:
            instance.perm_view = perms['view']; updated = True
        if instance.perm_modify_id != perms['modify'].id:
            instance.perm_modify = perms['modify']; updated = True
        if instance.perm_view_backups_id != perms['view_backups'].id:
            instance.perm_view_backups = perms['view_backups']; updated = True
        if instance.perm_backup_now_id != perms['backup_now'].id:
            instance.perm_backup_now = perms['backup_now']; updated = True
        if updated:
            instance.save(update_fields=['perm_view', 'perm_modify', 'perm_view_backups', 'perm_backup_now'])
        return instance

    def rename_to(self, new_group_name: str):
        """Update the human-readable permission names to reflect new group name."""
        permission_specs = [
            ('view', self.perm_view, f'Device Group - {new_group_name} - Can View'),
            ('modify', self.perm_modify, f'Device Group - {new_group_name} - Can Modify'),
            ('view_backups', self.perm_view_backups, f'Device Group - {new_group_name} - Can View Backups'),
            ('backup_now', self.perm_backup_now, f'Device Group - {new_group_name} - Can Backup Now'),
        ]
        
        for action, perm, expected in permission_specs:
            if perm.name != expected:
                perm.name = expected
                perm.save(update_fields=['name'])

    def has_any_holders(self) -> bool:
        # Any users with these permissions directly assigned
        if self.perm_view.user_set.exists() or self.perm_modify.user_set.exists() or self.perm_view_backups.user_set.exists() or self.perm_backup_now.user_set.exists():
            return True
        # Any groups with these permissions assigned
        if self.perm_view.group_set.exists() or self.perm_modify.group_set.exists() or self.perm_view_backups.group_set.exists() or self.perm_backup_now.group_set.exists():
            return True
        # Also consider our own role assignments as usage of this device group
        if 'UserDeviceGroupRole' in globals():
            from devices.models import UserDeviceGroupRole, GroupDeviceGroupRole
            if UserDeviceGroupRole.objects.filter(role__device_group=self.device_group).exists():
                return True
            if GroupDeviceGroupRole.objects.filter(role__device_group=self.device_group).exists():
                return True
        return False

@receiver(pre_delete, sender=DeviceGroup)
def prevent_delete_if_devices_exist(sender, instance, **kwargs):
    # Block deletion if any Device references this group
    from devices.models import Device
    if Device.objects.filter(device_group=instance).exists():
        from django.core.exceptions import ValidationError
        raise ValidationError('Cannot delete device group: devices are assigned to this group.')


class DeviceGroupPermission(models.Model):
    """
    DeviceGroupPermission Model: Granular permissions for device group operations
    
    Fields:
        - code (CharField): Unique permission code (e.g., "view_config", "view_backups", "edit_config", etc.)
        - name (CharField): Human-readable name for the permission
        - description (TextField): Description of what this permission allows
    
    Permission Codes:
        - view_configuration: Can view device configuration backups
        - view_backups: Can view/download backup history
        - edit_configuration: Can modify device configuration
        - add_device: Can add devices to the group
        - delete_device: Can delete devices from the group
        - enable_device: Can enable/disable devices in the group
    """
    code = models.CharField(max_length=50, unique=True, help_text='Unique permission code')
    name = models.CharField(max_length=100, help_text='Human-readable permission name')
    description = models.TextField(blank=True, help_text='Description of what this permission allows')
    
    class Meta:
        db_table = 'devices_devicegrouppermission'
        ordering = ['code']
    
    def __str__(self):
        """Return permission code for admin display"""
        return self.code


class DeviceGroupRole(models.Model):
    """
    DeviceGroupRole Model: Roles for managing access to device groups
    
    Fields:
        - name (CharField): Role name (e.g., "Operator", "Viewer", "Admin")
        - device_group (ForeignKey): Which device group this role applies to
        - description (TextField): Description of the role's purpose
        - permissions (ManyToManyField): Permissions granted by this role
        - created_at (DateTimeField): When role was created
    
    Methods:
        - __str__(): Returns role name with device group
    
    Usage:
        Roles are created per device group and grant specific permissions.
        Users and auth groups are then assigned these roles to control their access.
    """
    name = models.CharField(max_length=100, help_text='Role name within the device group')
    device_group = models.ForeignKey(DeviceGroup, on_delete=models.CASCADE, related_name='roles', help_text='Device group this role applies to')
    description = models.TextField(help_text='Description of the role')
    permissions = models.ManyToManyField(DeviceGroupPermission, blank=True, related_name='roles', help_text='Permissions granted by this role')
    created_at = models.DateTimeField(default=timezone.now, blank=True, null=True, help_text='When role was created')
    
    class Meta:
        db_table = 'devices_devicegrouprole'
        unique_together = ('name', 'device_group')
        ordering = ['device_group', 'name']
        verbose_name = 'Device Group Role'
        verbose_name_plural = 'Device Group Roles'
    
    def __str__(self):
        """Return role name with device group"""
        return f"{self.name} ({self.device_group.name})"


class UserDeviceGroupRole(models.Model):
    """
    UserDeviceGroupRole Model: Assigns device group roles to users
    
    Fields:
        - user (ForeignKey): User being assigned a role
        - role (ForeignKey): Device group role to assign
    
    Constraints:
        - Each user-role pair is unique (no duplicate assignments)
    
    Usage:
        Users are assigned roles for specific device groups.
        A user can have different roles for different device groups.
    """
    user = models.ForeignKey(User, on_delete=models.CASCADE, related_name='device_group_roles', help_text='User being assigned a role')
    role = models.ForeignKey(DeviceGroupRole, on_delete=models.CASCADE, help_text='Device group role to assign')
    
    class Meta:
        unique_together = ('user', 'role')
        verbose_name = 'User Device Group Role'
        verbose_name_plural = 'User Device Group Roles'
    
    def __str__(self):
        """Return descriptive string"""
        return f"{self.user.username} -> {self.role}"


class GroupDeviceGroupRole(models.Model):
    """
    GroupDeviceGroupRole Model: Assigns device group roles to Django auth groups
    
    Fields:
        - auth_group (ForeignKey): Django auth group
        - role (ForeignKey): Device group role to assign
    
    Constraints:
        - Each auth_group-role pair is unique (no duplicate assignments)
    
    Usage:
        Auth groups are assigned roles for specific device groups.
        All users in the auth group inherit the role and its permissions.
        This allows bulk assignment of device group access.
    """
    auth_group = models.ForeignKey(AuthGroup, on_delete=models.CASCADE, related_name='device_group_roles', help_text='Django auth group')
    role = models.ForeignKey(DeviceGroupRole, on_delete=models.CASCADE, help_text='Device group role to assign')
    
    class Meta:
        unique_together = ('auth_group', 'role')
        verbose_name = 'Group Device Group Role'
        verbose_name_plural = 'Group Device Group Roles'
    
    def __str__(self):
        """Return descriptive string"""
        return f"{self.auth_group.name} -> {self.role}"


# ===== Signals for DeviceGroup lifecycle management =====

@receiver(post_save, sender=DeviceGroup)
def ensure_django_permissions_on_save(sender, instance, created, **kwargs):
    # Always ensure permissions exist and reflect current group name
    link = DeviceGroupDjangoPermissions.ensure_for_group(instance)
    link.rename_to(instance.name)

@receiver(pre_delete, sender=DeviceGroup)
def prevent_delete_if_permissions_in_use(sender, instance, **kwargs):
    try:
        link = instance.django_permissions
    except DeviceGroupDjangoPermissions.DoesNotExist:
        return  # No mapping; allow deletion
    if link.has_any_holders():
        from django.core.exceptions import ValidationError
        raise ValidationError('Cannot delete device group: related Django permissions are assigned to users or groups.')

@receiver(pre_delete, sender=CollectionGroup)
def prevent_delete_if_devices_in_collection_group(sender, instance, **kwargs):
    """Block deletion of collection groups if any devices are assigned to them"""
    if instance.device_count > 0:
        from django.core.exceptions import ValidationError
        raise ValidationError(f'Cannot delete collection group "{instance.name}": {instance.device_count} device(s) are assigned to this group.')
