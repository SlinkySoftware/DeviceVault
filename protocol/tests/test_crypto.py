"""
Comprehensive test suite for DeviceVault backup encryption.

Tests cover:
    - Header codec (round-trip, malformed, edge cases)
    - Vault keys (public-key wrapping, rotation, wrong key, missing KID) and sealed values
    - Encryption engine (small/large payloads, empty, multi-chunk, uniqueness)
    - Tamper detection (ciphertext, header, AAD)
    - Backward compatibility (plaintext v0 passthrough)

Run with: make test

Copyright (C) 2026, Slinky Software
License: GPLv3+
"""

import os
import unittest

from devicevault_protocol.crypto import ecies, seal, unseal
from devicevault_protocol.crypto.constants import (
    CIPHER_ID,
    ENC_VERSION,
    GCM_NONCE_BYTES,
    HEADER_MAGIC,
)
from devicevault_protocol.crypto.engine import _zeroize, decrypt_backup, encrypt_backup
from devicevault_protocol.crypto.exceptions import (
    DecryptionError,
    HeaderError,
    KeyProviderError,
    KeyUnwrapError,
    MasterKeyNotFoundError,
    TamperDetectedError,
)
from devicevault_protocol.crypto.header import EncryptionHeader, is_encrypted
from devicevault_protocol.crypto.providers import VaultKeyRing


def _make_provider(*kids):
    """A vault key ring with fresh keys; the first kid is current."""
    return VaultKeyRing({kid: ecies.generate_private_key() for kid in kids})


# =========================================================================
# Header codec tests
# =========================================================================


class TestEncryptionHeader(unittest.TestCase):
    def test_roundtrip(self):
        """Header serialises and deserialises correctly."""
        hdr = EncryptionHeader(
            enc_version=1,
            cipher='AES-256-GCM',
            chunk_size=1048576,
            kid='test-key',
            edk=os.urandom(40),
            aad={'device_id': 42, 'backup_id': 'abc-123'},
        )
        data = hdr.to_bytes()
        parsed = EncryptionHeader.from_bytes(data)

        self.assertEqual(parsed.enc_version, 1)
        self.assertEqual(parsed.cipher, 'AES-256-GCM')
        self.assertEqual(parsed.chunk_size, 1048576)
        self.assertEqual(parsed.kid, 'test-key')
        self.assertEqual(parsed.edk, hdr.edk)
        self.assertEqual(parsed.aad, {'device_id': 42, 'backup_id': 'abc-123'})
        self.assertEqual(parsed.header_size, len(data))

    def test_empty_aad(self):
        """Header with empty AAD round-trips."""
        hdr = EncryptionHeader(kid='k', edk=b'\x00' * 40, aad={})
        data = hdr.to_bytes()
        parsed = EncryptionHeader.from_bytes(data)
        self.assertEqual(parsed.aad, {})

    def test_invalid_magic(self):
        """Parsing data with wrong magic raises HeaderError."""
        bad = b'XXXX' + b'\x00' * 100
        with self.assertRaises(HeaderError):
            EncryptionHeader.from_bytes(bad)

    def test_is_encrypted(self):
        """is_encrypted detects DVLT magic."""
        self.assertTrue(is_encrypted(HEADER_MAGIC + b'\x00' * 10))
        self.assertFalse(is_encrypted(b'plaintext backup content'))
        self.assertFalse(is_encrypted(b''))
        self.assertFalse(is_encrypted(b'DVL'))  # too short


# =========================================================================
# Encryption engine tests
# =========================================================================


class TestEncryptionEngine(unittest.TestCase):
    def setUp(self):
        self.kp = _make_provider('test-key')

    def test_small_payload_roundtrip(self):
        """Small text backup encrypts and decrypts correctly."""
        pt = b'hostname router-01\ninterface eth0\n'
        blob, meta = encrypt_backup(pt, self.kp, chunk_size=64 * 1024)
        recovered = decrypt_backup(blob, self.kp)
        self.assertEqual(recovered, pt)
        self.assertEqual(meta['enc_version'], ENC_VERSION)
        self.assertEqual(meta['cipher'], CIPHER_ID)

    def test_large_payload_multi_chunk(self):
        """Payload larger than chunk_size uses multiple chunks."""
        pt = os.urandom(300_000)  # 300 KB
        chunk_size = 64 * 1024  # 64 KB chunks -> ~5 chunks
        blob, meta = encrypt_backup(pt, self.kp, chunk_size=chunk_size)
        recovered = decrypt_backup(blob, self.kp)
        self.assertEqual(recovered, pt)

    def test_empty_payload(self):
        """Empty payload encrypts and decrypts to empty bytes."""
        blob, _ = encrypt_backup(b'', self.kp)
        recovered = decrypt_backup(blob, self.kp)
        self.assertEqual(recovered, b'')

    def test_one_byte_payload(self):
        """Single byte encrypts and decrypts correctly."""
        blob, _ = encrypt_backup(b'X', self.kp)
        recovered = decrypt_backup(blob, self.kp)
        self.assertEqual(recovered, b'X')

    def test_exact_chunk_boundary(self):
        """Payload exactly at chunk boundary doesn't produce empty trailing chunk."""
        chunk_size = 1024
        pt = os.urandom(chunk_size)
        blob, _ = encrypt_backup(pt, self.kp, chunk_size=chunk_size)
        recovered = decrypt_backup(blob, self.kp)
        self.assertEqual(recovered, pt)

    def test_exact_two_chunks(self):
        """Payload exactly at 2x chunk boundary."""
        chunk_size = 1024
        pt = os.urandom(chunk_size * 2)
        blob, _ = encrypt_backup(pt, self.kp, chunk_size=chunk_size)
        recovered = decrypt_backup(blob, self.kp)
        self.assertEqual(recovered, pt)

    def test_uniqueness(self):
        """Same plaintext encrypted twice produces different ciphertext."""
        pt = b'same data'
        blob1, _ = encrypt_backup(pt, self.kp)
        blob2, _ = encrypt_backup(pt, self.kp)
        self.assertNotEqual(blob1, blob2)

    def test_binary_payload(self):
        """Binary content (with null bytes) round-trips."""
        pt = bytes(range(256)) * 100
        blob, _ = encrypt_backup(pt, self.kp)
        recovered = decrypt_backup(blob, self.kp)
        self.assertEqual(recovered, pt)

    def test_aad_fields_included(self):
        """AAD fields are stored in header and used for authentication."""
        pt = b'test data'
        aad = {'device_id': 42, 'backup_id': 'test-123'}
        blob, meta = encrypt_backup(pt, self.kp, aad_fields=aad)
        # Verify AAD is in header
        hdr = EncryptionHeader.from_bytes(blob)
        self.assertEqual(hdr.aad['device_id'], 42)
        self.assertEqual(hdr.aad['backup_id'], 'test-123')
        # Still decryptable
        recovered = decrypt_backup(blob, self.kp)
        self.assertEqual(recovered, pt)


# =========================================================================
# Tamper detection tests
# =========================================================================


class TestTamperDetection(unittest.TestCase):
    def setUp(self):
        self.kp = _make_provider('tamper-key')
        self.pt = b'sensitive configuration data'
        self.blob, _ = encrypt_backup(self.pt, self.kp, chunk_size=64 * 1024)
        self.hdr = EncryptionHeader.from_bytes(self.blob)

    def test_ciphertext_tamper(self):
        """Flipping a bit in ciphertext raises TamperDetectedError."""
        tampered = bytearray(self.blob)
        # Flip a byte well into the ciphertext area
        pos = self.hdr.header_size + GCM_NONCE_BYTES + 5
        tampered[pos] ^= 0xFF
        with self.assertRaises(TamperDetectedError):
            decrypt_backup(bytes(tampered), self.kp)

    def test_nonce_tamper(self):
        """Flipping a bit in the nonce raises TamperDetectedError."""
        tampered = bytearray(self.blob)
        pos = self.hdr.header_size + 2  # inside the nonce
        tampered[pos] ^= 0xFF
        with self.assertRaises(TamperDetectedError):
            decrypt_backup(bytes(tampered), self.kp)

    def test_tag_tamper(self):
        """Modifying the GCM tag raises TamperDetectedError."""
        tampered = bytearray(self.blob)
        # Tag is at the end of the first (and only) chunk
        tampered[-1] ^= 0xFF
        with self.assertRaises(TamperDetectedError):
            decrypt_backup(bytes(tampered), self.kp)

    def test_corrupted_magic_treated_as_plaintext(self):
        """Corrupted magic bytes cause fallback to v0 plaintext."""
        tampered = bytearray(self.blob)
        tampered[0] ^= 0xFF
        result = decrypt_backup(bytes(tampered), self.kp)
        # Result is the corrupted blob itself (treated as plaintext)
        self.assertEqual(result, bytes(tampered))


# =========================================================================
# Backward compatibility tests
# =========================================================================


class TestBackwardCompatibility(unittest.TestCase):
    def setUp(self):
        self.kp = _make_provider('compat-key')

    def test_plaintext_passthrough(self):
        """Legacy plaintext data (no header) passes through unchanged."""
        legacy = b'hostname switch-01\nvlan 10\n'
        result = decrypt_backup(legacy, self.kp)
        self.assertEqual(result, legacy)

    def test_plaintext_string_passthrough(self):
        """Arbitrary string bytes (no DVLT magic) pass through."""
        data = b'just a plain text config'
        result = decrypt_backup(data, self.kp)
        self.assertEqual(result, data)

    def test_empty_bytes_passthrough(self):
        """Empty bytes pass through as v0 plaintext."""
        result = decrypt_backup(b'', self.kp)
        self.assertEqual(result, b'')


# =========================================================================
# Vault keys and sealed values
# =========================================================================


class TestVaultKeys(unittest.TestCase):
    def test_collectors_encrypt_with_the_public_key_only(self):
        ring = _make_provider('v1')
        blob, meta = encrypt_backup(b'running-config', ring.public())

        self.assertEqual(meta['kid'], 'v1')
        self.assertEqual(decrypt_backup(blob, ring), b'running-config')
        with self.assertRaises(KeyUnwrapError):
            decrypt_backup(blob, ring.public())

    def test_another_ring_cannot_unwrap(self):
        blob, _ = encrypt_backup(b'secret', _make_provider('v1').public())

        with self.assertRaises(KeyUnwrapError):
            decrypt_backup(blob, _make_provider('v1'))

    def test_unknown_kid_raises(self):
        blob, _ = encrypt_backup(b'secret', _make_provider('old').public())

        with self.assertRaises(MasterKeyNotFoundError):
            decrypt_backup(blob, _make_provider('new'))

    def test_rotation_keeps_old_backups_readable(self):
        old, new = ecies.generate_private_key(), ecies.generate_private_key()
        blob, _ = encrypt_backup(b'before rotation', VaultKeyRing({'k1': old}).public())

        rotated = VaultKeyRing({'k2': new, 'k1': old})

        self.assertEqual(rotated.current_kid, 'k2')
        self.assertEqual(decrypt_backup(blob, rotated), b'before rotation')
        self.assertEqual(encrypt_backup(b'after', rotated.public())[1]['kid'], 'k2')

    def test_key_ring_config(self):
        a, b = ecies.generate_private_key(), ecies.generate_private_key()
        text = f'k2={ecies.private_key_to_b64(b)}, k1={ecies.private_key_to_b64(a)}'

        ring = VaultKeyRing.from_config(text)

        self.assertEqual(ring.current_kid, 'k2')
        self.assertEqual(ring.public_key_b64('k1'), ecies.public_key_to_b64(a))
        for bad in ('', 'k1', 'k1=', 'k1=bm90IGEga2V5', f'k1={ecies.private_key_to_b64(a)},k1=x'):
            with self.subTest(bad=bad), self.assertRaises(KeyProviderError):
                VaultKeyRing.from_config(bad)

    def test_sealed_values_open_only_for_their_recipient(self):
        worker = ecies.generate_private_key()
        sealed = seal({'username': 'admin', 'password': 'p'}, worker.public_key())

        self.assertNotIn('admin', sealed)
        self.assertEqual(unseal(sealed, worker), {'username': 'admin', 'password': 'p'})
        with self.assertRaises(DecryptionError):
            unseal(sealed, ecies.generate_private_key())
        tampered = sealed[:-4] + ('AAAA' if not sealed.endswith('AAAA') else 'BBBB')
        with self.assertRaises(DecryptionError):
            unseal(tampered, worker)


# =========================================================================
# Zeroization test
# =========================================================================


class TestZeroize(unittest.TestCase):
    def test_zeroize(self):
        """_zeroize overwrites buffer with zeros."""
        buf = bytearray(b'secret key material')
        _zeroize(buf)
        self.assertEqual(buf, bytearray(len(b'secret key material')))


# =========================================================================
# Edge case / fuzz-like tests
# =========================================================================


class TestEdgeCases(unittest.TestCase):
    def setUp(self):
        self.kp = _make_provider('edge-key')

    def test_various_chunk_sizes(self):
        """Test with several chunk sizes from min to large."""
        pt = os.urandom(50_000)
        for chunk_size in [64 * 1024, 128 * 1024, 1024, 4096]:
            blob, _ = encrypt_backup(pt, self.kp, chunk_size=chunk_size)
            recovered = decrypt_backup(blob, self.kp)
            self.assertEqual(recovered, pt, f'Failed with chunk_size={chunk_size}')

    def test_payload_one_less_than_chunk(self):
        """Payload exactly chunk_size - 1."""
        cs = 4096
        pt = os.urandom(cs - 1)
        blob, _ = encrypt_backup(pt, self.kp, chunk_size=cs)
        self.assertEqual(decrypt_backup(blob, self.kp), pt)

    def test_payload_one_more_than_chunk(self):
        """Payload exactly chunk_size + 1."""
        cs = 4096
        pt = os.urandom(cs + 1)
        blob, _ = encrypt_backup(pt, self.kp, chunk_size=cs)
        self.assertEqual(decrypt_backup(blob, self.kp), pt)

    def test_unicode_content(self):
        """UTF-8 content with multibyte characters."""
        text = '日本語のバックアップ設定 — ñ € £ ★'.encode()
        blob, _ = encrypt_backup(text, self.kp)
        self.assertEqual(decrypt_backup(blob, self.kp), text)


if __name__ == '__main__':
    unittest.main()
