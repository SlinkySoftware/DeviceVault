"""Who may do what: the one place authorization is decided.

A user's permissions on a device group are the union of the grants of every
user group they belong to. Members of a global-administrator group hold every
permission on every device group (including devices in no group) and are the
only ones who administer the application. ``is_staff``/``is_superuser`` mean
nothing here.

Results are cached on the user object, which lives for one request.
"""

from django.contrib.auth.models import User
from django.db.models import Q
from rest_framework.permissions import SAFE_METHODS, BasePermission

from accounts.models import ADMINISTRATORS, FLAGS, DeviceGroupGrant, UserGroup, UserGroupMembership

ALL_FLAGS = frozenset(FLAGS)
_CACHE = '_dv_access'


def _cache(user) -> dict:
    cache = getattr(user, _CACHE, None)
    if cache is None:
        cache = {}
        setattr(user, _CACHE, cache)
    return cache


def forget(user) -> None:
    """Drop cached access for ``user`` (after changing its memberships in the same request)."""
    if user is not None and hasattr(user, _CACHE):
        delattr(user, _CACHE)


def is_global_admin(user) -> bool:
    if not (user and user.is_authenticated and user.is_active):
        return False
    cache = _cache(user)
    if 'global_admin' not in cache:
        cache['global_admin'] = UserGroupMembership.objects.filter(user=user, group__is_global_admin=True).exists()
    return cache['global_admin']


def grants_for(user) -> dict[int, frozenset[str]]:
    """``{device_group_id: flags}`` for every device group the user can see."""
    if not (user and user.is_authenticated and user.is_active):
        return {}
    cache = _cache(user)
    if 'grants' not in cache:
        if is_global_admin(user):
            from devices.models import DeviceGroup

            grants = dict.fromkeys(DeviceGroup.objects.values_list('id', flat=True), ALL_FLAGS)
        else:
            merged: dict[int, set[str]] = {}
            rows = DeviceGroupGrant.objects.filter(user_group__memberships__user=user).values('device_group_id', *FLAGS)
            for row in rows:
                held = merged.setdefault(row['device_group_id'], set())
                held.update(flag for flag in FLAGS if row[flag])
            grants = {group_id: frozenset(flags) for group_id, flags in merged.items()}
        cache['grants'] = grants
    return cache['grants']


def _group_id(device_group) -> int | None:
    return getattr(device_group, 'pk', device_group)


def can(user, flag: str, device_group) -> bool:
    """Whether ``user`` holds ``flag`` on ``device_group`` (a DeviceGroup, its id, or None for ungrouped)."""
    if is_global_admin(user):
        return True
    group_id = _group_id(device_group)
    return group_id is not None and flag in grants_for(user).get(group_id, ())


def flags_on(user, device_group) -> list[str]:
    """The flags ``user`` holds on ``device_group``, in FLAGS order."""
    if is_global_admin(user):
        return list(FLAGS)
    held = grants_for(user).get(_group_id(device_group), frozenset())
    return [flag for flag in FLAGS if flag in held]


def group_ids_with(user, flag: str) -> list[int]:
    """Device groups on which ``user`` holds ``flag`` (all of them for a global administrator)."""
    return [group_id for group_id, flags in grants_for(user).items() if flag in flags]


def administers_any(user) -> bool:
    return is_global_admin(user) or bool(group_ids_with(user, 'admin'))


def visible_device_groups(user):
    from devices.models import DeviceGroup

    if is_global_admin(user):
        return DeviceGroup.objects.all()
    return DeviceGroup.objects.filter(pk__in=list(grants_for(user)))


def devices_for(user, flag: str = 'view', queryset=None):
    """Devices on which ``user`` holds ``flag``; ungrouped devices only for global administrators."""
    from devices.models import Device

    devices = Device.objects.all() if queryset is None else queryset
    if is_global_admin(user):
        return devices
    return devices.filter(device_group_id__in=group_ids_with(user, flag))


def device_group_of(obj) -> int | None:
    """The device group id governing ``obj``: a device, or anything with a ``device``."""
    if hasattr(obj, 'device_group_id'):
        return obj.device_group_id
    return obj.device.device_group_id


def active_global_admins():
    return User.objects.filter(is_active=True, group_memberships__group__is_global_admin=True).distinct()


def administrators_group() -> UserGroup:
    """The built-in Administrators group, created on first use."""
    group = UserGroup.objects.filter(is_builtin=True).first()
    if group is None:
        # Adopt a hand-made group of that name rather than fail on the unique name.
        group, _ = UserGroup.objects.get_or_create(
            name=ADMINISTRATORS, defaults={'description': 'Built-in global administrators'}
        )
        group.is_builtin = group.is_global_admin = True
        group.source = UserGroup.INTERNAL
        group.save()
    return group


def credentials_for(user, queryset=None):
    """Credentials ``user`` may see: global ones, and those owned by groups they administer."""
    from credentials.models import Credential

    credentials = Credential.objects.all() if queryset is None else queryset
    if is_global_admin(user):
        return credentials
    return credentials.filter(Q(device_group__isnull=True) | Q(device_group_id__in=group_ids_with(user, 'admin')))


# ===== DRF permission classes =====


class IsGlobalAdmin(BasePermission):
    """Application administration: global administrators only."""

    message = 'Only global administrators may do this.'

    def has_permission(self, request, view):
        return is_global_admin(request.user)


class IsGlobalAdminOrReadOnly(BasePermission):
    """Any signed-in user may read; only global administrators may write (shared reference data)."""

    message = 'Only global administrators may change this.'

    def has_permission(self, request, view):
        if request.method in SAFE_METHODS:
            return bool(request.user and request.user.is_authenticated)
        return is_global_admin(request.user)


class CanReadMonitoring(BasePermission):
    """The read-only monitoring endpoints: any signed-in user or token (``monitoring`` or ``api`` scope).

    The figures are filtered to the caller's ``view`` grants; platform sections
    are left out unless ``sees_platform``.
    """

    def has_permission(self, request, view):
        return bool(request.user and request.user.is_authenticated and request.method in SAFE_METHODS)


def sees_platform(request) -> bool:
    """Platform health (workers, scheduler, storage targets, receivers): admin-only facts elsewhere in the API.

    A token needs the ``monitoring_platform`` scope; a session needs a global administrator.
    """
    from accounts.models import ApiToken

    token = getattr(request, 'auth', None)
    if isinstance(token, ApiToken):
        return ApiToken.MONITORING_PLATFORM in token.scopes
    return is_global_admin(request.user)


class HasDeviceGroupPermission(BasePermission):
    """Signed-in users, holding ``flag`` on the device group of the object acted on.

    Used as ``permission_classes = [HasDeviceGroupPermission('download')]``: DRF
    instantiates permission classes by calling them, which returns this instance.
    """

    def __init__(self, flag: str = 'view'):
        if flag not in FLAGS:
            raise ValueError(f'Unknown permission flag {flag!r}')
        self.flag = flag
        self.message = f'You need the "{flag}" permission on this device group.'

    def __call__(self):
        return self

    def has_permission(self, request, view):
        return bool(request.user and request.user.is_authenticated)

    def has_object_permission(self, request, view, obj):
        return can(request.user, self.flag, device_group_of(obj))
