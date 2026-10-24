"""User groups, their members, and the permissions they grant on device groups.

Access is the union of the grants of every group a user belongs to; a member
of a group flagged ``is_global_admin`` holds everything. See accounts.access,
the only place these are interpreted.
"""

from django.contrib.auth.models import User
from django.db import models
from django.db.models import Q

# Permission flags on a device group, weakest first.
VIEW = 'view'
BACKUP_NOW = 'backup_now'
VIEW_CONTENTS = 'view_contents'
DOWNLOAD = 'download'
ADMIN = 'admin'
FLAGS = (VIEW, BACKUP_NOW, VIEW_CONTENTS, DOWNLOAD, ADMIN)

# What each flag needs besides itself (admin needs everything).
REQUIRES = {
    VIEW: (),
    BACKUP_NOW: (VIEW,),
    VIEW_CONTENTS: (VIEW,),
    DOWNLOAD: (VIEW_CONTENTS,),
    ADMIN: (VIEW, BACKUP_NOW, VIEW_CONTENTS, DOWNLOAD),
}

ADMINISTRATORS = 'Administrators'


class UserGroup(models.Model):
    """A named set of users. Internal groups are managed by hand; external ones by an identity provider."""

    INTERNAL = 'internal'
    EXTERNAL = 'external'
    SOURCE_CHOICES = [(INTERNAL, 'Internal'), (EXTERNAL, 'External')]

    name = models.CharField(max_length=150, unique=True)
    description = models.TextField(blank=True)
    is_global_admin = models.BooleanField(
        default=False, help_text='Members hold every permission on every device group and administer the application'
    )
    is_builtin = models.BooleanField(default=False, editable=False, help_text='The Administrators group')
    source = models.CharField(max_length=16, choices=SOURCE_CHOICES, default=INTERNAL)
    members = models.ManyToManyField(User, through='UserGroupMembership', related_name='user_groups', blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['name']

    def __str__(self):
        return self.name


class UserGroupMembership(models.Model):
    """A user's membership of a group, tagged with what added it (``manual`` or an identity provider)."""

    MANUAL = 'manual'

    user = models.ForeignKey(User, on_delete=models.CASCADE, related_name='group_memberships')
    group = models.ForeignKey(UserGroup, on_delete=models.CASCADE, related_name='memberships')
    source = models.CharField(max_length=64, default=MANUAL)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        constraints = [models.UniqueConstraint(fields=['user', 'group'], name='accounts_membership_unique')]

    def __str__(self):
        return f'{self.user.username} in {self.group.name}'


class DeviceGroupGrant(models.Model):
    """What members of ``user_group`` may do with the devices of ``device_group``.

    Every row includes ``view``; delete the row to revoke access.
    """

    user_group = models.ForeignKey(UserGroup, on_delete=models.CASCADE, related_name='grants')
    device_group = models.ForeignKey('devices.DeviceGroup', on_delete=models.CASCADE, related_name='grants')
    view = models.BooleanField(default=True, help_text='See the group, its devices and their backup jobs')
    backup_now = models.BooleanField(default=False, help_text='Start a backup now')
    view_contents = models.BooleanField(default=False, help_text='See and compare backup contents')
    download = models.BooleanField(default=False, help_text='Download backup contents')
    admin = models.BooleanField(default=False, help_text="Manage the group's devices and credentials")

    class Meta:
        ordering = ['user_group__name', 'device_group__name']
        constraints = [
            models.UniqueConstraint(fields=['user_group', 'device_group'], name='accounts_grant_unique'),
            models.CheckConstraint(condition=Q(view=True), name='accounts_grant_needs_view'),
            models.CheckConstraint(
                condition=Q(download=False) | Q(view_contents=True), name='accounts_grant_download_needs_contents'
            ),
            models.CheckConstraint(
                condition=Q(admin=False) | Q(backup_now=True, view_contents=True, download=True),
                name='accounts_grant_admin_needs_all',
            ),
        ]

    def __str__(self):
        return f'{self.user_group.name} on {self.device_group.name}: {", ".join(self.flags())}'

    def flags(self) -> list[str]:
        return [flag for flag in FLAGS if getattr(self, flag)]
