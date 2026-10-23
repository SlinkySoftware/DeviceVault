"""Encryption to an X25519 public key (ECIES).

A fresh ephemeral X25519 key agrees a secret with the recipient's key; HKDF
turns it into a one-time AES-256 key bound to both public keys and a
purpose label. Only the holder of the recipient's private key can derive it.

Used to wrap backup DEKs to the orchestrator vault key and to seal secrets
(device credentials, storage config) to individual workers.
"""

import json
import os
from typing import Any

from cryptography.exceptions import InvalidTag
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.asymmetric.x25519 import X25519PrivateKey, X25519PublicKey
from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from cryptography.hazmat.primitives.kdf.hkdf import HKDF
from cryptography.hazmat.primitives.serialization import Encoding, NoEncryption, PrivateFormat, PublicFormat

from devicevault_protocol.crypto.constants import AES_KEY_BYTES, GCM_NONCE_BYTES
from devicevault_protocol.crypto.exceptions import DecryptionError
from devicevault_protocol.signing import b64decode, b64encode

X25519_KEY_BYTES = 32

# Purpose labels: a key derived for one use can never decrypt another.
PURPOSE_DEK = b'devicevault/dek-wrap/v1'
PURPOSE_SEALED = b'devicevault/sealed/v1'


def generate_private_key() -> X25519PrivateKey:
    return X25519PrivateKey.generate()


def public_bytes(key: X25519PublicKey | X25519PrivateKey) -> bytes:
    if isinstance(key, X25519PrivateKey):
        key = key.public_key()
    return key.public_bytes(Encoding.Raw, PublicFormat.Raw)


def private_key_to_b64(key: X25519PrivateKey) -> str:
    return b64encode(key.private_bytes(Encoding.Raw, PrivateFormat.Raw, NoEncryption()))


def private_key_from_b64(value: str) -> X25519PrivateKey:
    raw = b64decode(value)
    if len(raw) != X25519_KEY_BYTES:
        raise ValueError(f'an X25519 private key is {X25519_KEY_BYTES} bytes, got {len(raw)}')
    return X25519PrivateKey.from_private_bytes(raw)


def public_key_to_b64(key: X25519PublicKey | X25519PrivateKey) -> str:
    return b64encode(public_bytes(key))


def public_key_from_b64(value: str) -> X25519PublicKey:
    raw = b64decode(value)
    if len(raw) != X25519_KEY_BYTES:
        raise ValueError(f'an X25519 public key is {X25519_KEY_BYTES} bytes, got {len(raw)}')
    return X25519PublicKey.from_public_bytes(raw)


def _derive(shared: bytes, ephemeral: bytes, recipient: bytes, purpose: bytes) -> bytes:
    return HKDF(algorithm=hashes.SHA256(), length=AES_KEY_BYTES, salt=ephemeral + recipient, info=purpose).derive(
        shared
    )


def agree(recipient: X25519PublicKey, purpose: bytes) -> tuple[bytes, bytes]:
    """Sender side: ``(ephemeral_public_bytes, key)``."""
    ephemeral = X25519PrivateKey.generate()
    epk = public_bytes(ephemeral)
    return epk, _derive(ephemeral.exchange(recipient), epk, public_bytes(recipient), purpose)


def recover(private: X25519PrivateKey, ephemeral_public: bytes, purpose: bytes) -> bytes:
    """Recipient side: the key ``agree`` produced for ``ephemeral_public``."""
    if len(ephemeral_public) != X25519_KEY_BYTES:
        raise DecryptionError('invalid ephemeral public key')
    shared = private.exchange(X25519PublicKey.from_public_bytes(ephemeral_public))
    return _derive(shared, ephemeral_public, public_bytes(private), purpose)


# --- sealed values ---------------------------------------------------------------


def seal(value: Any, recipient: X25519PublicKey) -> str:
    """JSON ``value`` encrypted so only ``recipient`` can read it, as a compact string."""
    epk, key = agree(recipient, PURPOSE_SEALED)
    nonce = os.urandom(GCM_NONCE_BYTES)
    plaintext = json.dumps(value, separators=(',', ':')).encode('utf-8')
    return b64encode(epk + nonce + AESGCM(key).encrypt(nonce, plaintext, epk))


def unseal(sealed: str, private: X25519PrivateKey) -> Any:
    try:
        raw = b64decode(sealed)
        epk, nonce, ciphertext = (
            raw[:X25519_KEY_BYTES],
            raw[X25519_KEY_BYTES : X25519_KEY_BYTES + GCM_NONCE_BYTES],
            raw[X25519_KEY_BYTES + GCM_NONCE_BYTES :],
        )
        key = recover(private, epk, PURPOSE_SEALED)
        return json.loads(AESGCM(key).decrypt(nonce, ciphertext, epk))
    except (InvalidTag, ValueError, TypeError) as exc:
        raise DecryptionError('sealed value could not be opened with this key') from exc
