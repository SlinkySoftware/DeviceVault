# Binary Backup Support - Implementation Guide

## Overview

DeviceVault now supports both text-based and binary-based configuration backups. This guide explains how the system works and how to extend it for custom binary backup types.

---

## Architecture Summary

### Plugin System

All backup methods are plugins defined in `backend/backups/plugins/`. Each plugin declares:
- **key**: Unique identifier (e.g., `mikrotik_ssh_export`)
- **friendly_name**: Human-readable name for UI
- **description**: What devices and method
- **is_binary**: True for binary, False for text (NEW)
- **entrypoint**: Function that executes the backup

### Data Flow

```
Device Collection → Collector Worker → Redis Stream → Storage → API → Frontend
     (Plugin)           (Celery)         (Results)      (FS/Git)   (REST)  (UI)
```

**Key Points**:
1. **Plugin** determines if backup is text or binary by setting `is_binary` flag
2. **Collector Worker** propagates `is_binary` in Redis stream (worker stays stateless)
3. **Orchestrator** (not shown) consumes stream, detects `is_binary`, and calls storage with correct mode
4. **Storage** handles both text and binary modes
5. **Frontend** disables view/diff for binary, enables download for both

---

## For Text Backups (Existing Behavior)

No changes required. All existing plugins continue to work:

```python
# backend/backups/plugins/your_text_plugin.py

from .base import BackupPlugin
from datetime import datetime

def _collect_config(config: Dict, timeout: Optional[int] = None) -> Dict:
    """Collect text configuration."""
    ip = config.get('ip')
    creds = config.get('credentials', {})
    
    try:
        # Connect to device and retrieve config as text
        config_text = ssh_connect_and_get_config(ip, creds, timeout)
        
        return {
            'task_id': None,
            'status': 'success',
            'timestamp': datetime.utcnow().isoformat() + 'Z',
            'log': ['config_collected'],
            'device_config': config_text  # Plain string
        }
    except Exception as exc:
        return {
            'task_id': None,
            'status': 'failure',
            'timestamp': datetime.utcnow().isoformat() + 'Z',
            'log': [str(exc)],
            'device_config': None
        }

PLUGIN = BackupPlugin(
    key='text_plugin',
    friendly_name='Text Config Plugin',
    description='Collects text-based device configuration.',
    entrypoint=_collect_config,
    is_binary=False  # or omit (defaults to False)
)
```

---

## For Binary Backups (New Feature)

Create a new plugin with `is_binary=True`:

```python
# backend/backups/plugins/firmware_binary.py

from .base import BackupPlugin
from datetime import datetime
import base64

def _collect_firmware(config: Dict, timeout: Optional[int] = None) -> Dict:
    """Collect binary firmware."""
    ip = config.get('ip')
    creds = config.get('credentials', {})
    
    try:
        # Download binary firmware from device
        binary_data = tftp_download_firmware(ip, creds, timeout)
        
        # IMPORTANT: Return as base64-encoded string (JSON serializable)
        encoded = base64.b64encode(binary_data).decode('ascii')
        
        return {
            'task_id': None,
            'status': 'success',
            'timestamp': datetime.utcnow().isoformat() + 'Z',
            'log': [f'Downloaded {len(binary_data)} bytes'],
            'device_config': encoded  # BASE64 STRING (not raw bytes)
        }
    except Exception as exc:
        return {
            'task_id': None,
            'status': 'failure',
            'timestamp': datetime.utcnow().isoformat() + 'Z',
            'log': [str(exc)],
            'device_config': None
        }

PLUGIN = BackupPlugin(
    key='firmware_binary',
    friendly_name='Firmware Binary Export',
    description='Downloads device firmware as binary blob via TFTP.',
    entrypoint=_collect_firmware,
    is_binary=True  # <-- CRITICAL for binary plugins
)
```

### Key Requirements for Binary Plugins

1. **Set `is_binary=True`** in `PLUGIN` definition
2. **Return base64-encoded string** in `device_config` field (JSON serializable)
3. **Log messages** should document size: `f'Downloaded {len(binary_data)} bytes'`

### Why Base64?

Binary data must be JSON-serializable to pass through:
- Redis streams (worker → orchestrator)
- HTTP JSON APIs (orchestrator → storage worker)

Base64 overhead is ~33% (250 MB → 333 MB), which is acceptable for:
- Simplicity (no complex streaming plumbing)
- Reliability (standard JSON encoding/decoding)
- Compatibility (works with all storage backends)

**Alternative**: For very large files (250+ MB), you could implement streaming directly from device to storage (bypass Redis), but this adds architectural complexity. The current approach handles 250 MB with minimal overhead.

---

## Frontend Behavior

### Text Backups
- ✅ View button - displays inline in modal
- ✅ Compare button - performs line-based diff with another text backup
- ✅ Download - exports as .txt file

### Binary Backups
- ❌ View button - disabled (binary not human-readable)
- ❌ Compare button - disabled (diff algorithm requires text)
- ✅ Download - exports as .bin file

### UI Indicators

Table columns show:
- **Type**: "Text" or "Binary" for each backup
- **View Icon**: Eye icon only for text backups
- **Download Icon**: Default icon for text, cloud icon for binary

---

## Configuration

### Enable Binary Plugin

1. Create plugin file: `backend/backups/plugins/your_binary_plugin.py`
2. Set `is_binary=True` in `PLUGIN` definition
3. Restart Django: `./devicevault.sh restart`
4. Plugin appears in Backup Methods admin page
5. Assign to devices: Edit Device → Backup Method → Select your plugin
6. Run backup: scheduled or manual trigger

### API Response Example

**GET `/api/backup-methods/`**

```json
[
  {
    "key": "mikrotik_ssh_export",
    "friendly_name": "Mikrotik SSH Export",
    "description": "...",
    "is_binary": false
  },
  {
    "key": "firmware_binary",
    "friendly_name": "Firmware Binary Export",
    "description": "...",
    "is_binary": true
  }
]
```

### Backup Record Example

**GET `/api/stored-backups/?device=1`**

```json
{
  "id": 42,
  "device_id": 1,
  "status": "success",
  "timestamp": "2026-01-13T10:30:00Z",
  "is_text": false,  # <-- Indicates binary
  "storage_backend": "filesystem",
  "storage_ref": "backup_method=firmware_binary/device_1/2026-01-13-103000.bin"
}
```

---

## Storage Behavior

### Filesystem Storage (`backend/storage/fs.py`)

- **Text**: Written with UTF-8 encoding, mode `'w'`
- **Binary**: Written as raw bytes, mode `'wb'`
- Base64-encoded strings from plugins are decoded before storage
- Both modes support up to filesystem limits (typically 16 EB on ext4)

### Git Storage (`backend/storage/git.py`)

- **Text**: Committed as text blobs
- **Binary**: Committed as binary blobs (Git handles natively)
- Same encoding/decoding as filesystem storage

Both backends handle 250 MB files efficiently with standard read/write operations.

---

## Testing Binary Plugins

### Manual Test with Demo Plugin

1. Ensure plugin is loaded:
   ```bash
   curl -H "Authorization: Token <TOKEN>" http://localhost:8000/api/backup-methods/
   ```

2. Should see `binary_dummy` plugin listed with `"is_binary": true`

3. Assign to a device in Django admin:
   - Edit Device → Backup Method → "Binary Dummy (Demo)" → Save

4. Trigger backup manually (via admin or schedule)

5. Check backups table:
   - Type should show "Binary"
   - View button should be disabled
   - Download button should work and save as `.bin` file

### Verify Storage

Check filesystem:
```bash
ls -lh /path/to/backup/storage/backup_method=binary_dummy/device_*/
```

Should see `.bin` files with correct size (1 MB for demo plugin).

---

## Common Issues & Troubleshooting

### Issue: "Plugin not discovered"

**Cause**: Plugin file not in `backend/backups/plugins/` or missing `PLUGIN` variable

**Fix**: 
- Ensure file is in correct directory
- Verify `PLUGIN = BackupPlugin(...)` is defined
- Restart Django: `./devicevault.sh restart`
- Check logs: `tail -f logs/devicevault.log`

### Issue: "View/Download returns error for binary backup"

**Cause**: Storage backend called without `is_binary=True`

**Fix**:
- Verify `Backup.is_text` field is set correctly in database
- Check orchestrator code: ensure it passes `is_binary` to storage functions
- Verify base64 encoding/decoding in plugin result

### Issue: "Binary file corrupted after download"

**Cause**: Encoding/decoding mismatch between plugin and storage

**Fix**:
- Ensure plugin returns base64-encoded string (not raw bytes)
- Verify storage decodes correctly before writing binary mode
- Check API response: binary download should return `application/octet-stream` MIME type
- Use file comparison: `diff <(file.bin) <(expected.bin)` or `hexdump`

---

## API Endpoints (Updated)

### List Backup Methods
```
GET /api/backup-methods/

Response:
[
  {
    "key": "...",
    "friendly_name": "...",
    "description": "...",
    "is_binary": bool
  }
]
```

### Download Backup
```
GET /api/stored-backups/{id}/download/

For text: Returns JSON with 'content' field
For binary: Returns binary file (application/octet-stream)
```

The endpoint automatically detects backup type via `backup_result.is_text` and returns appropriate response.

---

## Database Field Reference

### Backup Model

```python
class Backup(models.Model):
    ...
    is_text = models.BooleanField(default=True, help_text='True if text artifact (configs), False if binary')
```

**Populated by**: Orchestrator when creating backup record
**Source**: Plugin's `is_binary` flag (inverse: `is_text = not plugin.is_binary`)

### DeviceBackupResult Model

Shows latest backup status, includes reference to actual Backup record via join.

---

## Performance Considerations

### For 250 MB Binary Files

1. **Data Transfer** (Base64 overhead): +33% = ~333 MB
2. **Redis Stream**: Default size limit 500 MB, no issue
3. **Storage Write**: Standard file I/O, no chunking needed
4. **API Download**: Django HttpResponse handles streaming efficiently
5. **Memory Usage**: Loaded into memory once per operation (acceptable for 250 MB)

### Optimization Options (Future)

- **Chunked Upload**: Stream from device directly to storage (bypass Redis)
- **Compression**: Gzip binary before base64 encoding (~50-80% reduction)
- **S3/Cloud Storage**: Stream to cloud backends (S3, Azure Blob)
- **Streaming Download**: HTTP range requests for resume capability

Current implementation prioritizes **simplicity** and **reliability** over maximum efficiency.

---

## Migration Notes

### For Existing Installations

No database migrations required. All fields exist:
- `Backup.is_text` defaults to `True`
- `BackupPlugin.is_binary` defaults to `False`
- All existing plugins continue to work unchanged

### For New Installations

Binary backup support is available immediately upon first startup.

---

## Creating Production Binary Plugins

Template for TFTP-based firmware download:

```python
import paramiko
import base64
from typing import Dict, Optional, Any
from datetime import datetime

def _download_firmware_via_tftp(config: Dict[str, Any], timeout: Optional[int] = None) -> Dict[str, Any]:
    """Download firmware from device via TFTP."""
    ip = config.get('ip')
    creds = config.get('credentials', {})
    username = creds.get('username')
    password = creds.get('password')
    
    try:
        # Connect via SSH to trigger TFTP download
        client = paramiko.SSHClient()
        client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
        client.connect(ip, username=username, password=password, timeout=timeout or 10)
        
        # Execute command to download firmware to temp location
        chan = client.exec_command('copy running-config tftp://server/backup.bin')
        chan.recv_exit_status()
        
        # Download via TFTP
        import socket
        sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        # TFTP read request (RRQ)
        # ... TFTP protocol implementation ...
        firmware_bytes = b'...'  # Downloaded binary
        sock.close()
        client.close()
        
        encoded = base64.b64encode(firmware_bytes).decode('ascii')
        
        return {
            'task_id': None,
            'status': 'success',
            'timestamp': datetime.utcnow().isoformat() + 'Z',
            'log': [f'Downloaded {len(firmware_bytes)} bytes via TFTP'],
            'device_config': encoded
        }
    except Exception as exc:
        return {
            'task_id': None,
            'status': 'failure',
            'timestamp': datetime.utcnow().isoformat() + 'Z',
            'log': [f'TFTP download failed: {exc}'],
            'device_config': None
        }

PLUGIN = BackupPlugin(
    key='firmware_tftp_download',
    friendly_name='Firmware TFTP Download',
    description='Downloads device firmware via TFTP protocol.',
    entrypoint=_download_firmware_via_tftp,
    is_binary=True
)
```

---

## Related Files Modified

### Backend
- `backend/backups/plugins/base.py` - Added `is_binary` field to `BackupPlugin`
- `backend/backups/plugins/__init__.py` - Exposes `is_binary` in API
- `backend/backups/plugins/binary_dummy.py` - Demo binary plugin (NEW)
- `backend/backups/storage_client.py` - Accepts `is_binary` parameter
- `backend/storage/fs.py` - Handles binary mode write/read
- `backend/storage/git.py` - Handles binary mode write/read
- `backend/devicevault_worker.py` - Propagates `is_binary` in Redis stream
- `backend/api/views.py` - Updated download endpoint for binary support
- `backend/backups/models.py` - `is_text` field (already exists, now used)

### Frontend
- `frontend/src/pages/ViewBackups.vue` - Type column, conditional view/compare buttons

### Documentation
- `docs/BINARY_BACKUP_SUPPORT.md` - Architectural analysis (NEW)
- `docs/BINARY_BACKUP_IMPLEMENTATION.md` - This file (NEW)

---

## Next Steps

1. **Test Binary Plugins**: Use `binary_dummy` plugin to verify end-to-end functionality
2. **Create Custom Plugins**: Implement for your device types (TFTP, SCP, etc.)
3. **Monitor Storage**: Ensure sufficient disk space for binary backups (250 MB each)
4. **Set Retention Policies**: Archive/delete old binary backups to manage space

---

## Support

For issues or questions:
1. Check `logs/devicevault.log` for error messages
2. Review `docs/BINARY_BACKUP_SUPPORT.md` for architectural details
3. Run demo plugin to verify system is working
4. Consult plugin implementation examples in `backend/backups/plugins/`

