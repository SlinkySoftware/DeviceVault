"""DEK wrapping for backup content: collectors wrap to the vault public key,
the orchestrator unwraps with the vault private key ring.

An encrypted DEK (``edk``) is ``ephemeral_public (32) || AES-KW(kek, dek)``,
where ``kek`` comes from X25519 + HKDF (see ``ecies``). The key id (``kid``)
in the backup header names the vault key, so keys can be rotated: new
backups use the current key, older ones still decrypt while their key stays
in the ring.
"""

from abc import ABC, abstractmethod

from cryptography.hazmat.primitives.asymmetric.x25519 import X25519PrivateKey, X25519PublicKey
from cryptography.hazmat.primitives.keywrap import InvalidUnwrap, aes_key_unwrap, aes_key_wrap

from devicevault_protocol.crypto import ecies
from devicevault_protocol.crypto.exceptions import KeyProviderError, KeyUnwrapError, MasterKeyNotFoundError


class KeyProvider(ABC):
    @abstractmethod
    def wrap_key(self, dek: bytes) -> tuple[bytes, str]:
        """``(edk, kid)`` for a new backup."""

    def unwrap_key(self, edk: bytes, kid: str) -> bytes:
        raise KeyUnwrapError('this key provider cannot decrypt')


def _wrap(public: X25519PublicKey, dek: bytes) -> bytes:
    epk, kek = ecies.agree(public, ecies.PURPOSE_DEK)
    return epk + aes_key_wrap(kek, dek)


class VaultPublicKey(KeyProvider):
    """The collector side: can encrypt backups, never decrypt them."""

    def __init__(self, kid: str, public_key_b64: str):
        if not kid:
            raise KeyProviderError('a vault key needs a key id')
        self.kid = kid
        try:
            self.public_key = ecies.public_key_from_b64(public_key_b64)
        except ValueError as exc:
            raise KeyProviderError(f'invalid vault public key: {exc}') from exc

    def wrap_key(self, dek: bytes) -> tuple[bytes, str]:
        return _wrap(self.public_key, dek), self.kid


def parse_key_ring(text: str, name: str) -> dict[str, str]:
    """``kid=value,kid=value`` (the first entry is current) as an ordered dict."""
    ring = {}
    for item in filter(None, (part.strip() for part in (text or '').split(','))):
        kid, sep, value = item.partition('=')
        if not sep or not kid.strip() or not value.strip():
            raise KeyProviderError(f'{name}: expected kid=<base64 key>, got "{item[:12]}..."')
        if kid.strip() in ring:
            raise KeyProviderError(f'{name}: duplicate key id "{kid.strip()}"')
        ring[kid.strip()] = value.strip()
    return ring


class VaultKeyRing(KeyProvider):
    """The orchestrator side: every vault private key, the first one current."""

    def __init__(self, keys: dict[str, X25519PrivateKey]):
        if not keys:
            raise KeyProviderError('the vault key ring is empty')
        self._keys = dict(keys)
        self.current_kid = next(iter(self._keys))

    @classmethod
    def from_config(cls, text: str) -> VaultKeyRing:
        try:
            keys = {
                kid: ecies.private_key_from_b64(value) for kid, value in parse_key_ring(text, 'DV_VAULT_KEYS').items()
            }
        except ValueError as exc:
            raise KeyProviderError(f'DV_VAULT_KEYS: {exc}') from exc
        return cls(keys)

    def public_key_b64(self, kid: str | None = None) -> str:
        return ecies.public_key_to_b64(self._key(kid or self.current_kid))

    def public(self) -> VaultPublicKey:
        """What collectors get: the current key's id and public half."""
        return VaultPublicKey(self.current_kid, self.public_key_b64())

    def _key(self, kid: str) -> X25519PrivateKey:
        try:
            return self._keys[kid]
        except KeyError:
            raise MasterKeyNotFoundError(f'vault key "{kid}" is not in DV_VAULT_KEYS') from None

    def wrap_key(self, dek: bytes) -> tuple[bytes, str]:
        return _wrap(self._key(self.current_kid).public_key(), dek), self.current_kid

    def unwrap_key(self, edk: bytes, kid: str) -> bytes:
        private = self._key(kid)
        epk, wrapped = edk[: ecies.X25519_KEY_BYTES], edk[ecies.X25519_KEY_BYTES :]
        try:
            return aes_key_unwrap(ecies.recover(private, epk, ecies.PURPOSE_DEK), wrapped)
        except (InvalidUnwrap, ValueError) as exc:
            raise KeyUnwrapError(f'the backup key could not be unwrapped with vault key "{kid}"') from exc
