# Backup Encryption at Rest

> **Status**: Implemented (v1)  
> **Algorithm**: AES-256-GCM with envelope encryption  
> **Standard references**: NIST SP 800-38D (GCM), RFC 3394 (AES Key Wrap), NIST SP 800-57 (Key Management)

## Overview

DeviceVault encrypts backup data at rest using **envelope encryption**. Each
backup object is encrypted with a unique Data Encryption Key (DEK), and the
DEK is wrapped (encrypted) by a master key before being stored in the
encrypted object header. This design ensures:

- **Key isolation**: Compromise of a single DEK affects only one backup.
- **Efficient rotation**: Rotating the master key only requires re-wrapping
  stored EDKs — the backup ciphertext is untouched.
- **Tamper detection**: AES-GCM authentication tags on every chunk detect any
  modification to the ciphertext, nonce, or additional authenticated data.

## Per-Device Encryption

Encryption is controlled **per device** via the "Encrypt backups at rest"
toggle on the device configuration page. When enabled:

- All **new** backups for that device are encrypted using AES-256-GCM.
- Existing backups are **not** retroactively encrypted.
- Turning the toggle off means subsequent backups are stored as plaintext.
- Encrypted and plaintext backups can coexist for the same device.

In the backup history view, a 🔒 **lock icon** indicates encrypted backups,
while an unlocked icon indicates plaintext backups.

> **Prerequisite**: At least one master key must be configured in
> `config.yaml` (or via environment variable) for per-device encryption to
> work. If no key is available, a warning is logged and the backup is stored
> as plaintext.

## Architecture

```
                         ┌──────────────────────────┐
                         │    Master Key (KEK)       │
                         │  256-bit AES key          │
                         │  stored in config.yaml    │
                         │  or env variable          │
                         └─────────┬────────────────┘
                                   │
                          AES Key Wrap (RFC 3394)
                                   │
     ┌─────────────────────────────▼─────────────────────────────┐
     │             Encrypted Object (stored on disk)             │
     │                                                           │
     │  ┌───────────────────────────────────────────────────┐    │
     │  │  Binary Header                                    │    │
     │  │  ─────────────────────────────────────────────    │    │
     │  │  Magic: DVLT (4 bytes)                            │    │
     │  │  enc_version: 1                                   │    │
     │  │  cipher: AES-256-GCM                              │    │
     │  │  chunk_size: 1048576 (1 MiB)                      │    │
     │  │  KID: master key identifier                       │    │
     │  │  EDK: wrapped DEK (40 bytes)                      │    │
     │  │  AAD: JSON metadata (device_id, task_id, etc.)    │    │
     │  └───────────────────────────────────────────────────┘    │
     │                                                           │
     │  ┌───────────────────────────────────────────────────┐    │
     │  │  Chunk 0                                          │    │
     │  │  [12-byte nonce][ciphertext + 16-byte GCM tag]    │    │
     │  └───────────────────────────────────────────────────┘    │
     │  ┌───────────────────────────────────────────────────┐    │
     │  │  Chunk 1                                          │    │
     │  │  [12-byte nonce][ciphertext + 16-byte GCM tag]    │    │
     │  └───────────────────────────────────────────────────┘    │
     │  ...                                                      │
     └───────────────────────────────────────────────────────────┘
```

### Encryption flow

1. Generate a fresh 256-bit DEK using `os.urandom(32)`.
2. Wrap the DEK with the default master key via AES Key Wrap (RFC 3394).
3. Build the binary header with magic, version, cipher ID, KID, EDK, and AAD.
4. Split plaintext into fixed-size chunks (default 1 MiB).
5. For each chunk: generate a unique 12-byte random nonce, encrypt with
   AES-256-GCM binding the AAD, append `[nonce][ciphertext+tag]`.
6. Concatenate header + all encrypted chunks to produce the final blob.
7. Zeroize the plaintext DEK from memory.

### Decryption flow

1. Check for `DVLT` magic bytes. If absent, return data as-is (v0 plaintext).
2. Parse the binary header to extract KID, EDK, chunk_size, AAD.
3. Look up the master key by KID in the key ring.
4. Unwrap the EDK → plaintext DEK using AES Key Unwrap.
5. For each chunk: read nonce + ciphertext+tag, decrypt with AESGCM + AAD.
6. Concatenate plaintext chunks. Zeroize the DEK.

## Configuration

Encryption requires master keys to be configured in `backend/config/config.yaml`
(or via environment variables). The per-device toggle controls whether
encryption is applied; the config provides the key material.

### config.yaml

```yaml
encryption:
  # The 'enabled' flag can be set to true for global enforcement, but
  # per-device encryption works even when this is false — as long as
  # at least one key is configured below.
  enabled: false

  default_key_id: mk-2025           # KID for new writes
  chunk_size_bytes: 1048576         # Bytes per chunk (default 1 MiB)
  allow_plaintext_fallback: true    # Allow reading v0 plaintext backups

  keys:
    mk-2025: <base64-encoded-32-byte-key>
```

### Environment variable overrides

| Variable | Overrides | Type |
|---|---|---|
| `DEVICEVAULT_ENCRYPTION_ENABLED` | `encryption.enabled` | bool |
| `DEVICEVAULT_LOCAL_MASTER_KEY` | Single master key (fallback) | base64 string |
| `DEVICEVAULT_KEY_PROVIDER` | `encryption.key_provider` | `local` |
| `DEVICEVAULT_CHUNK_SIZE_BYTES` | `encryption.chunk_size_bytes` | int |
| `DEVICEVAULT_ALLOW_PLAINTEXT_FALLBACK` | `encryption.allow_plaintext_fallback` | bool |

### Generating a master key

```bash
cd backend
source ../.venv/bin/activate
python manage.py encryption_keys generate
```

This outputs a cryptographically random 256-bit key encoded as base64. Copy
the output and paste it into your `config.yaml` under `encryption.keys`.

## Key Management CLI

The `encryption_keys` management command provides key management operations:

```bash
cd backend && source ../.venv/bin/activate

# Show encryption status
python manage.py encryption_keys status

# List configured key IDs
python manage.py encryption_keys list

# Generate a new 256-bit key
python manage.py encryption_keys generate

# Instructions for setting a new default key
python manage.py encryption_keys set-default <kid>

# Rewrap EDKs from one master key to another (key rotation)
python manage.py encryption_keys rewrap --from old-kid --to new-kid
```

## Key Rotation

Master key rotation is a two-step process that does **not** require
re-encrypting any backup data:

1. **Add the new key** to `config.yaml` under `encryption.keys` and set it as
   `default_key_id`. Keep the old key in the ring.

2. **Rewrap existing EDKs**:
   ```bash
   python manage.py encryption_keys rewrap --from mk-2025 --to mk-2026
   ```
   This reads each `StoredBackup` record encrypted with the old KID, unwraps
   the EDK using the old master key, re-wraps it with the new master key, and
   updates the database record. The encrypted backup blob on disk is
   **not modified** — only the EDK in the database changes.

3. After verifying all backups decrypt correctly, remove the old key from the
   config.

> **Important**: The EDK stored in the binary header on disk still references
> the old KID. The `rewrap` command updates only the `enc_edk` and `enc_kid`
> fields in the database. The storage worker uses the database fields for
> decryption when available, and falls back to the embedded header EDK.

## Backward Compatibility

- **v0 (plaintext)**: Backups created before encryption was enabled have no
  `DVLT` header. The decryption path detects this and returns data as-is.
- **Mixed environment**: Encrypted and plaintext backups can coexist for the
  same device. The `StoredBackup.enc_version` field is `NULL` or `0` for
  plaintext backups and `1` for encrypted backups.
- **Per-device toggle**: Toggling encryption off for a device does **not**
  decrypt existing encrypted backups. They remain encrypted and readable.
  Only new backups going forward will be stored as plaintext.

## Database Schema

The `StoredBackup` model includes four encryption metadata fields:

| Field | Type | Description |
|---|---|---|
| `enc_version` | IntegerField (nullable) | Encryption format version (1 = AES-256-GCM) |
| `enc_cipher` | CharField (nullable) | Cipher identifier (e.g., `AES-256-GCM`) |
| `enc_kid` | CharField (nullable) | Master key identifier used for wrapping |
| `enc_edk` | TextField (nullable) | Base64-encoded encrypted DEK |

These fields are populated by the storage consumer when processing results
from the storage worker Redis stream.

The `Device` model includes:

| Field | Type | Description |
|---|---|---|
| `encrypt_backups` | BooleanField (default: False) | Per-device toggle for encryption at rest |

## Module Structure

```
backend/crypto/
├── __init__.py       # Public API exports
├── constants.py      # Cryptographic constants and configuration keys
├── exceptions.py     # Exception hierarchy
├── header.py         # Binary header codec (EncryptionHeader)
├── providers.py      # KeyProvider ABC + LocalKeyProvider
├── engine.py         # encrypt_backup() / decrypt_backup() core logic
├── wrapper.py        # CryptoStorage transparent driver wrapper
├── config.py         # Configuration loader (YAML + env vars)
└── tests/
    ├── __init__.py
    └── test_crypto.py  # 43 unit tests covering all components
```

## Security Properties

| Property | Mechanism |
|---|---|
| Confidentiality | AES-256-GCM (256-bit key, NIST SP 800-38D) |
| Integrity | GCM 128-bit authentication tag per chunk |
| Authentication | AAD includes backup metadata, bound to every chunk |
| Key isolation | Fresh random DEK per backup |
| Key protection | AES Key Wrap (RFC 3394 / NIST SP 800-38F) |
| Nonce uniqueness | 12-byte CSPRNG nonce per chunk |
| Memory safety | DEK zeroized after use (best-effort for Python) |
| Fail-closed | Encryption enabled + missing key → error (no plaintext fallback) |
| Tamper detection | Any bit flip in nonce/ciphertext/tag raises `TamperDetectedError` |

## Threat Model

### In scope
- **Disk theft / offline access**: Encrypted backups are unreadable without
  the master key.
- **Database compromise**: EDKs in the database are AES-Key-Wrapped and
  require the master key to unwrap.
- **Backup file tampering**: GCM tags detect any modification.
- **Chunk reordering/truncation**: Each chunk has a unique nonce; reordering
  or truncation causes GCM authentication failure.

### Out of scope (defence-in-depth, not primary goals)
- **Memory forensics**: Python GC may retain copies of key material.
- **Side-channel attacks**: No constant-time guarantees in Python.
- **Master key exfiltration from running process**: If the process memory is
  compromised, the master key is accessible. Use KMS integration (future
  release) for stronger protection.

## Testing

Run the test suite:

```bash
cd backend
source ../.venv/bin/activate
python -m pytest crypto/tests/ -v
```

The test suite includes 43 tests covering:
- Header codec round-trips and malformed input
- Key provider wrap/unwrap, rotation, error paths
- Encryption engine: small, large, empty, binary, multi-chunk payloads
- Tamper detection: ciphertext, nonce, and tag corruption
- Backward compatibility: plaintext v0 passthrough
- CryptoStorage wrapper: mock driver store/read
- Key rotation: multi-key ring, rewrap simulation
- Edge cases: boundary chunk sizes, Unicode content
- Memory zeroization

## Future Enhancements

- **KMS integration**: `KmsKeyProvider` for AWS KMS, Azure Key Vault, or
  HashiCorp Vault (master key never leaves KMS boundary).
- **Streaming I/O**: Currently buffers entire backup in memory. Future
  versions may support true streaming encryption for very large backups.
- **Per-tenant keys**: Multi-tenancy support with separate key rings per
  device group.
- **Audit logging**: Cryptographic operations logged to the audit trail.
