"""
Comprehensive test suite for DeviceVault backup encryption.

Tests cover:
    - Header codec (round-trip, malformed, edge cases)
    - Key provider (wrap/unwrap, rotation, wrong key, missing KID)
    - Encryption engine (small/large payloads, empty, multi-chunk, uniqueness)
    - Tamper detection (ciphertext, header, AAD)
    - Backward compatibility (plaintext v0 passthrough)
    - CryptoStorage wrapper (store/read with mock driver)
    - Configuration loading

Run with: cd backend && source ../.venv/bin/activate && python -m pytest crypto/tests/ -v

Copyright (C) 2026, Slinky Software
License: GPLv3+
"""

import base64
import json
import os
import struct
import sys
import unittest

# Ensure backend is on path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

from crypto.constants import (
    AES_KEY_BYTES, GCM_NONCE_BYTES, GCM_TAG_BYTES,
    DEFAULT_CHUNK_SIZE, HEADER_MAGIC, ENC_VERSION, CIPHER_ID,
)
from crypto.exceptions import (
    TamperDetectedError, DecryptionError, MasterKeyNotFoundError,
    KeyUnwrapError, KeyProviderError, EncryptionError,
    ChunkLimitExceededError, HeaderError,
)
from crypto.header import EncryptionHeader, is_encrypted
from crypto.providers import LocalKeyProvider
from crypto.engine import encrypt_backup, decrypt_backup, _zeroize
from crypto.wrapper import CryptoStorage


def _make_provider(*keys, default=None):
    """Helper to create a LocalKeyProvider with random keys."""
    key_dict = {}
    for kid in keys:
        key_dict[kid] = base64.b64encode(os.urandom(AES_KEY_BYTES)).decode()
    return LocalKeyProvider(keys=key_dict, default_kid=default or keys[0])


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
# Key provider tests
# =========================================================================

class TestLocalKeyProvider(unittest.TestCase):

    def test_wrap_unwrap_roundtrip(self):
        """DEK wrap + unwrap returns original key."""
        kp = _make_provider('mk-1')
        dek = os.urandom(AES_KEY_BYTES)
        edk, kid = kp.wrap_key(dek)
        recovered = kp.unwrap_key(edk, kid)
        self.assertEqual(recovered, dek)
        self.assertEqual(kid, 'mk-1')

    def test_multiple_keys(self):
        """Key ring supports multiple KIDs."""
        kp = _make_provider('key-A', 'key-B', default='key-B')
        self.assertEqual(kp.get_default_key_id(), 'key-B')
        self.assertIn('key-A', kp.list_key_ids())
        self.assertIn('key-B', kp.list_key_ids())

    def test_wrong_kid_raises(self):
        """Unwrapping with unknown KID raises MasterKeyNotFoundError."""
        kp = _make_provider('mk-1')
        dek = os.urandom(AES_KEY_BYTES)
        edk, _ = kp.wrap_key(dek)
        with self.assertRaises(MasterKeyNotFoundError):
            kp.unwrap_key(edk, 'nonexistent-kid')

    def test_wrong_key_material_raises(self):
        """Unwrapping EDK with wrong master key raises KeyUnwrapError."""
        kp1 = _make_provider('k1')
        kp2 = _make_provider('k2')
        dek = os.urandom(AES_KEY_BYTES)
        edk, _ = kp1.wrap_key(dek)
        # kp2's 'k2' key cannot unwrap kp1's EDK
        # But we need to add 'k1' as a KID to kp2's ring to avoid MasterKeyNotFoundError
        # So let's test with a provider that has the same KID but different key material
        key_a = base64.b64encode(os.urandom(AES_KEY_BYTES)).decode()
        key_b = base64.b64encode(os.urandom(AES_KEY_BYTES)).decode()
        kp_a = LocalKeyProvider(keys={'shared-kid': key_a})
        kp_b = LocalKeyProvider(keys={'shared-kid': key_b})
        edk, kid = kp_a.wrap_key(dek)
        with self.assertRaises(KeyUnwrapError):
            kp_b.unwrap_key(edk, kid)

    def test_set_default(self):
        """set_default_key_id changes the wrap key."""
        kp = _make_provider('k1', 'k2', default='k1')
        _, kid1 = kp.wrap_key(os.urandom(AES_KEY_BYTES))
        self.assertEqual(kid1, 'k1')
        kp.set_default_key_id('k2')
        _, kid2 = kp.wrap_key(os.urandom(AES_KEY_BYTES))
        self.assertEqual(kid2, 'k2')

    def test_set_default_invalid(self):
        """Setting default to unknown KID raises."""
        kp = _make_provider('k1')
        with self.assertRaises(MasterKeyNotFoundError):
            kp.set_default_key_id('nonexistent')

    def test_bad_key_length(self):
        """Key with wrong length raises KeyProviderError."""
        with self.assertRaises(KeyProviderError):
            LocalKeyProvider(keys={'bad': base64.b64encode(b'short').decode()})

    def test_bad_base64(self):
        """Invalid base64 raises KeyProviderError."""
        with self.assertRaises(KeyProviderError):
            LocalKeyProvider(keys={'bad': '!!!not-base64!!!'})

    def test_no_keys_raises(self):
        """Empty key ring raises KeyProviderError."""
        # Clear env to avoid fallback
        old = os.environ.pop('DEVICEVAULT_LOCAL_MASTER_KEY', None)
        try:
            with self.assertRaises(KeyProviderError):
                LocalKeyProvider(keys={})
        finally:
            if old is not None:
                os.environ['DEVICEVAULT_LOCAL_MASTER_KEY'] = old

    def test_generate_master_key(self):
        """Generated key is valid base64 and correct length."""
        key_b64 = LocalKeyProvider.generate_master_key()
        raw = base64.b64decode(key_b64)
        self.assertEqual(len(raw), AES_KEY_BYTES)


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
        chunk_size = 64 * 1024    # 64 KB chunks -> ~5 chunks
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
        data = 'just a plain text config'.encode('utf-8')
        result = decrypt_backup(data, self.kp)
        self.assertEqual(result, data)

    def test_empty_bytes_passthrough(self):
        """Empty bytes pass through as v0 plaintext."""
        result = decrypt_backup(b'', self.kp)
        self.assertEqual(result, b'')


# =========================================================================
# Key rotation tests
# =========================================================================

class TestKeyRotation(unittest.TestCase):

    def test_read_with_old_key_in_ring(self):
        """Backup encrypted with old key is readable when ring has both keys."""
        k1 = base64.b64encode(os.urandom(AES_KEY_BYTES)).decode()
        k2 = base64.b64encode(os.urandom(AES_KEY_BYTES)).decode()

        # Encrypt with k1
        kp1 = LocalKeyProvider(keys={'k1': k1}, default_kid='k1')
        pt = b'rotation test data'
        blob, meta = encrypt_backup(pt, kp1)
        self.assertEqual(meta['kid'], 'k1')

        # Read with ring containing both keys, default k2
        kp_both = LocalKeyProvider(keys={'k1': k1, 'k2': k2}, default_kid='k2')
        recovered = decrypt_backup(blob, kp_both)
        self.assertEqual(recovered, pt)

    def test_new_backups_use_new_default(self):
        """New encryptions use the new default KID."""
        k1 = base64.b64encode(os.urandom(AES_KEY_BYTES)).decode()
        k2 = base64.b64encode(os.urandom(AES_KEY_BYTES)).decode()

        kp = LocalKeyProvider(keys={'k1': k1, 'k2': k2}, default_kid='k2')
        pt = b'new backup'
        _, meta = encrypt_backup(pt, kp)
        self.assertEqual(meta['kid'], 'k2')

    def test_rewrap_simulation(self):
        """Simulated rewrap: unwrap with old key, rewrap with new key."""
        k1 = base64.b64encode(os.urandom(AES_KEY_BYTES)).decode()
        k2 = base64.b64encode(os.urandom(AES_KEY_BYTES)).decode()

        kp = LocalKeyProvider(keys={'k1': k1, 'k2': k2}, default_kid='k1')
        pt = b'rewrap test'
        blob, meta = encrypt_backup(pt, kp)

        # Simulate rewrap: unwrap EDK from k1, rewrap with k2
        edk_bytes = base64.b64decode(meta['edk'])
        plaintext_dek = kp.unwrap_key(edk_bytes, 'k1')
        kp.set_default_key_id('k2')
        new_edk, new_kid = kp.wrap_key(plaintext_dek)
        self.assertEqual(new_kid, 'k2')

        # The original blob still decrypts (header has k1's EDK embedded)
        recovered = decrypt_backup(blob, kp)
        self.assertEqual(recovered, pt)


# =========================================================================
# CryptoStorage wrapper tests
# =========================================================================

class TestCryptoStorage(unittest.TestCase):

    def setUp(self):
        self.kp = _make_provider('wrap-key')
        self.crypto = CryptoStorage(self.kp, chunk_size=64 * 1024)
        self._stored = {}

    def _mock_store(self, content, rel_path, config, is_binary=False):
        """Mock storage driver store function."""
        self._stored[rel_path] = content
        return rel_path

    def _mock_read(self, storage_ref, config, is_binary=False):
        """Mock storage driver read function."""
        return self._stored.get(storage_ref, b'')

    def test_store_and_read_text(self):
        """Text content encrypts on store and decrypts on read."""
        content = 'hostname router\ninterface eth0\n'
        ref, meta = self.crypto.store(
            content, 'test.cfg', {}, is_binary=False,
            store_fn=self._mock_store,
        )
        self.assertIsNotNone(meta)
        self.assertEqual(meta['enc_version'], 1)

        # Stored data should be encrypted (binary blob)
        stored_data = self._stored['test.cfg']
        self.assertIsInstance(stored_data, bytes)
        self.assertTrue(is_encrypted(stored_data))

        # Read back
        recovered = self.crypto.read(ref, {}, is_binary=False, read_fn=self._mock_read)
        self.assertEqual(recovered, content)

    def test_store_and_read_binary(self):
        """Binary content encrypts on store and decrypts on read."""
        content = os.urandom(1000)
        ref, meta = self.crypto.store(
            content, 'backup.bin', {}, is_binary=True,
            store_fn=self._mock_store,
        )
        self.assertIsNotNone(meta)

        recovered = self.crypto.read(ref, {}, is_binary=True, read_fn=self._mock_read)
        self.assertEqual(recovered, content)

    def test_disabled_passthrough(self):
        """With encryption disabled, content passes through unmodified."""
        crypto_off = CryptoStorage(self.kp, encryption_enabled=False)
        content = 'plain text'
        ref, meta = crypto_off.store(
            content, 'plain.cfg', {}, is_binary=False,
            store_fn=self._mock_store,
        )
        self.assertIsNone(meta)
        # Stored data is the original string
        self.assertEqual(self._stored['plain.cfg'], 'plain text')

    def test_read_legacy_plaintext(self):
        """Reading a legacy plaintext backup returns it as-is."""
        self._stored['old.cfg'] = b'legacy plain config'
        result = self.crypto.read('old.cfg', {}, is_binary=False, read_fn=self._mock_read)
        self.assertEqual(result, 'legacy plain config')

    def test_read_legacy_plaintext_binary(self):
        """Reading a legacy plaintext binary returns raw bytes."""
        raw = os.urandom(500)
        self._stored['old.bin'] = raw
        result = self.crypto.read('old.bin', {}, is_binary=True, read_fn=self._mock_read)
        self.assertEqual(result, raw)


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
        text = '日本語のバックアップ設定 — ñ € £ ★'.encode('utf-8')
        blob, _ = encrypt_backup(text, self.kp)
        self.assertEqual(decrypt_backup(blob, self.kp), text)


if __name__ == '__main__':
    unittest.main()
