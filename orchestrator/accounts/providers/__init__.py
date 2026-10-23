"""Kinds of identity provider, keyed by ``AuthProvider.kind``."""

from accounts.providers.base import ExternalLogin, ProviderError, ProviderKind
from accounts.providers.ldap import LdapKind

KINDS: dict[str, ProviderKind] = {kind.key: kind for kind in (LdapKind(),)}

__all__ = ['KINDS', 'ExternalLogin', 'ProviderError', 'ProviderKind']
