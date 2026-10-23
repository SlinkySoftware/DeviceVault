"""User groups, their members, the permissions they grant on device groups, and identity providers.

Access is the union of the grants of every group a user belongs to; a member
of a group flagged ``is_global_admin`` holds everything. See accounts.access,
the only place these are interpreted.

Identity providers (LDAP, OIDC) are records edited in the UI. An external user
is linked to a provider by an immutable subject, never by username or email;
the provider's groups map onto user groups at each sign-in (accounts.login).
"""

from django.contrib.auth.models import User
from django.db import models
from django.db.models import Q

from core.fields import EncryptedJSONField

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
    provider = models.ForeignKey(
        'AuthProvider',
        on_delete=models.CASCADE,
        null=True,
        blank=True,
        related_name='groups',
        help_text='The identity provider an external group comes from',
    )
    external_id = models.CharField(max_length=255, blank=True, help_text="The provider's name for an external group")
    members = models.ManyToManyField(User, through='UserGroupMembership', related_name='user_groups', blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['name']
        constraints = [
            models.UniqueConstraint(
                fields=['provider', 'external_id'],
                condition=Q(provider__isnull=False),
                name='accounts_external_group_unique',
            ),
        ]

    def __str__(self):
        return self.name


class UserGroupMembership(models.Model):
    """A user's membership of a group, tagged with what added it: ``manual``, or the slug of the
    identity provider whose group sync added it (which only ever changes its own rows)."""

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


class AuthProvider(models.Model):
    """An identity provider users can sign in with. ``config`` is validated against the kind's settings model."""

    LDAP = 'ldap'
    OIDC = 'oidc'
    KIND_CHOICES = [(LDAP, 'LDAP / Active Directory'), (OIDC, 'OpenID Connect')]

    slug = models.SlugField(max_length=50, unique=True, help_text='Fixed once created; tags memberships and URLs')
    name = models.CharField(max_length=128)
    kind = models.CharField(max_length=16, choices=KIND_CHOICES)
    enabled = models.BooleanField(default=True)
    order = models.PositiveIntegerField(default=0, help_text='Password providers are tried in this order')
    config = EncryptedJSONField(default=dict, help_text='Settings for the kind (encrypted at rest)')
    auto_create_users = models.BooleanField(default=True, help_text='Create users on their first sign-in')
    auto_create_groups = models.BooleanField(
        default=False, help_text='Turn provider groups no rule maps into external user groups (with no grants)'
    )
    login_group = models.CharField(
        max_length=255, blank=True, help_text='If set, only members of this provider group may sign in'
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['order', 'name']

    def __str__(self):
        return self.name


class GroupMappingRule(models.Model):
    """Members of the provider group ``external_group`` belong to ``user_group``."""

    provider = models.ForeignKey(AuthProvider, on_delete=models.CASCADE, related_name='mapping_rules')
    external_group = models.CharField(max_length=255, help_text='Exact name (case-insensitive for LDAP)')
    user_group = models.ForeignKey(UserGroup, on_delete=models.CASCADE, related_name='mapping_rules')

    class Meta:
        ordering = ['external_group']
        constraints = [
            models.UniqueConstraint(
                fields=['provider', 'external_group', 'user_group'], name='accounts_mapping_rule_unique'
            ),
        ]

    def __str__(self):
        return f'{self.provider.slug}:{self.external_group} -> {self.user_group.name}'


class ExternalIdentity(models.Model):
    """Links a user to a provider by the provider's immutable subject (OIDC ``sub``, an LDAP identity attribute)."""

    provider = models.ForeignKey(AuthProvider, on_delete=models.CASCADE, related_name='identities')
    subject = models.CharField(max_length=255)
    user = models.ForeignKey(User, on_delete=models.CASCADE, related_name='external_identities')
    created_at = models.DateTimeField(auto_now_add=True)
    last_login_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        constraints = [models.UniqueConstraint(fields=['provider', 'subject'], name='accounts_identity_unique')]

    def __str__(self):
        return f'{self.user.username} at {self.provider.slug}'
