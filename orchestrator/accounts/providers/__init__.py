"""Kinds of identity provider, keyed by ``AuthProvider.kind``."""

from accounts.providers.base import ExternalLogin, ProviderError, ProviderKind
from accounts.providers.ldap import LdapKind
from accounts.providers.oidc import OidcKind

KINDS: dict[str, ProviderKind] = {kind.key: kind for kind in (LdapKind(), OidcKind())}

__all__ = ['KINDS', 'ExternalLogin', 'ProviderError', 'ProviderKind']
