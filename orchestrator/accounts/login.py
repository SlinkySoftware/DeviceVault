"""Signing in with a password (local accounts, then each enabled password provider in order),
and what happens when a provider vouches for a user: linking, provisioning and group sync.

An external login links only on (provider, subject). It never matches an existing
user by username or email, so whoever controls a directory entry or an IdP's email
claim cannot take over another account.
"""

import logging
from dataclasses import dataclass, field

from django.conf import settings
from django.contrib.auth import authenticate
from django.contrib.auth.models import User
from django.db import transaction
from django.utils import timezone

from accounts import access
from accounts.models import AuthProvider, ExternalIdentity, UserGroup, UserGroupMembership
from accounts.providers import KINDS, ExternalLogin, ProviderError

logger = logging.getLogger('devicevault.auth')


class LoginRefused(Exception):
    """The provider vouched for the user, but they may not sign in. ``reason`` goes to the audit log."""

    def __init__(self, reason: str):
        super().__init__(reason)
        self.reason = reason


@dataclass
class SignIn:
    user: User | None = None
    provider: AuthProvider | None = None
    reason: str = 'bad_credentials'
    details: dict = field(default_factory=dict)


def is_break_glass(user) -> bool:
    from core.models import UserProfile

    return UserProfile.objects.filter(user=user, break_glass=True).exists()


def is_service_account(user) -> bool:
    from core.models import UserProfile

    return UserProfile.objects.filter(user=user, is_service_account=True).exists()


def password_sign_in(request, username: str, password: str) -> SignIn:
    """Local accounts first, then each enabled password provider in ``order``."""
    result = SignIn()
    local = authenticate(request, username=username, password=password)
    if local is not None and is_service_account(local):
        # Service accounts have no usable password, so this guards against one being set by hand.
        return SignIn(reason='service_account')
    if local is not None:
        if settings.DEVICEVAULT_LOCAL_AUTH_ENABLED or is_break_glass(local):
            return SignIn(user=local, details={'provider': 'local'})
        result.reason = 'local_auth_disabled'

    providers = AuthProvider.objects.filter(enabled=True, kind__in=[k for k, v in KINDS.items() if v.password_login])
    for provider in providers:
        kind = KINDS[provider.kind]
        try:
            login = kind.authenticate(kind.config(provider.config), username, password)
        except ProviderError as exc:
            logger.warning('provider_unavailable', extra={'provider': provider.slug, 'error': str(exc)})
            result.details.setdefault('unavailable', []).append(provider.slug)
            continue
        if login is None:
            continue
        try:
            user, changes = accept(provider, login)
        except LoginRefused as exc:
            return SignIn(provider=provider, reason=exc.reason, details={'provider': provider.slug})
        return SignIn(user=user, provider=provider, details={'provider': provider.slug, **changes})
    return result


def _matches(provider: AuthProvider, wanted: str, names: list[str]) -> bool:
    if KINDS[provider.kind].case_insensitive_groups:
        return wanted.casefold() in {name.casefold() for name in names}
    return wanted in names


def unique_username(wanted: str) -> str:
    base = (wanted or 'user')[:140]
    candidate, n = base, 1
    while User.objects.filter(username__iexact=candidate).exists():
        n += 1
        candidate = f'{base}-{n}'
    return candidate


@transaction.atomic
def accept(provider: AuthProvider, login: ExternalLogin) -> tuple[User, dict]:
    """The user ``login`` is (created on first sign-in), with profile and groups refreshed.

    Raises LoginRefused when the provider's rules keep them out.
    """
    if provider.login_group and not _matches(provider, provider.login_group, login.groups):
        raise LoginRefused('not_in_login_group')
    identity = ExternalIdentity.objects.select_related('user').filter(provider=provider, subject=login.subject).first()
    created = False
    if identity is not None:
        user = identity.user
        if not user.is_active:
            raise LoginRefused('inactive')
    else:
        if not provider.auto_create_users:
            raise LoginRefused('not_provisioned')
        user = User(username=unique_username(login.username or login.subject))
        user.set_unusable_password()
        user.save()
        identity = ExternalIdentity.objects.create(provider=provider, subject=login.subject, user=user)
        created = True

    user.email, user.first_name, user.last_name = login.email[:254], login.first_name[:150], login.last_name[:150]
    user.save(update_fields=['email', 'first_name', 'last_name'])
    identity.last_login_at = timezone.now()
    identity.save(update_fields=['last_login_at'])
    added, removed = sync_groups(provider, user, login.groups)
    changes = {'groups_added': added, 'groups_removed': removed}
    if created:
        changes['created'] = True
    return user, changes


def sync_groups(provider: AuthProvider, user: User, names: list[str]) -> tuple[list[str], list[str]]:
    """Set the user's memberships sourced from ``provider`` to exactly what ``names`` map to.

    Mapping rules pick user groups; with ``auto_create_groups``, names no rule maps
    become external groups (``<slug>:<name>``, no grants). The provider's existing
    external groups match by name too. Manual memberships are never touched.
    """
    targets: set[int] = set()
    mapped: set[str] = set()
    for rule in provider.mapping_rules.all():
        if _matches(provider, rule.external_group, names):
            targets.add(rule.user_group_id)
            mapped.add(rule.external_group.casefold())
    fold = KINDS[provider.kind].case_insensitive_groups
    known = {(g.external_id.casefold() if fold else g.external_id): g for g in provider.groups.all()}
    for name in names:
        key = name.casefold() if fold else name
        group = known.get(key)
        if group is None and provider.auto_create_groups and name.casefold() not in mapped:
            group = UserGroup.objects.create(
                name=_unique_group_name(f'{provider.slug}:{name}'),
                source=UserGroup.EXTERNAL,
                provider=provider,
                external_id=name,
            )
            known[key] = group
        if group is not None:
            targets.add(group.pk)

    current = UserGroupMembership.objects.filter(user=user, source=provider.slug)
    gone = current.exclude(group_id__in=targets)
    removed = sorted(gone.values_list('group__name', flat=True))
    gone.delete()
    have = set(UserGroupMembership.objects.filter(user=user).values_list('group_id', flat=True))
    new = [group_id for group_id in targets if group_id not in have]
    UserGroupMembership.objects.bulk_create(
        UserGroupMembership(user=user, group_id=group_id, source=provider.slug) for group_id in new
    )
    added = sorted(UserGroup.objects.filter(pk__in=new).values_list('name', flat=True))
    access.forget(user)
    return added, removed


def _unique_group_name(wanted: str) -> str:
    candidate, n = wanted[:150], 1
    while UserGroup.objects.filter(name=candidate).exists():
        n += 1
        candidate = f'{wanted[:140]} ({n})'
    return candidate
