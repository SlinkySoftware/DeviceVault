# Binary Backup Support - Implementation Summary

## What Was Implemented

DeviceVault now supports **binary configuration backups** alongside the existing text-based approach. Binary backups are transferred, stored, and downloadable, but without in-browser viewing or diff capabilities.

---

## Changes Made

### 1. Plugin Interface (`backend/backups/plugins/base.py`)

Added `is_binary: bool = False` field to `BackupPlugin` dataclass.

```python
@dataclass
class BackupPlugin:
    key: str
    friendly_name: str
    description: str
    entrypoint: CollectorCallable
    is_binary: bool = False  # NEW
```

**Impact**:
- All existing plugins default to `is_binary=False` (backward compatible)
- Binary plugins explicitly set `is_binary=True`
- Plugin metadata propagated to frontend for UI decisions

### 2. API Endpoint (`backend/api/views.py`)

Updated `BackupMethodViewSet.list()` to expose `is_binary` flag:

```python
data = [
    {
        'key': p.key,
        'friendly_name': p.friendly_name,
        'description': p.description,
        'is_binary': p.is_binary  # NEW
    }
    for p in plugins
]
```

**Impact**: Frontend can detect binary plugins when assigning to devices.

### 3. Storage Backends

#### Filesystem (`backend/storage/fs.py`)
- Added `is_binary: bool = False` parameter to `store_backup()` and `read_backup()`
- Binary mode writes with `'wb'` instead of `'w'`
- Automatically decodes base64 strings before binary write
- Supports files up to filesystem limits (250 MB is trivial)

#### Git (`backend/storage/git.py`)
- Same changes as filesystem storage
- Git handles binary blobs natively

**Impact**: Both storage backends transparently handle binary and text data.

### 4. Collector Task (`backend/devicevault_worker.py`)

Updated `device_collect_task()` to propagate `is_binary` flag in Redis stream:

```python
payload = {
    'task_id': tid or '',
    'task_identifier': task_identifier or '',
    ...
    'is_binary': str(plugin.is_binary),  # NEW
}
redis_client.xadd(RESULTS_STREAM, payload)
```

**Impact**: 
- Worker remains stateless (doesn't know about storage)
- Orchestrator can detect binary and call storage with correct mode
- Redis stream is JSON-compatible (all values are strings)

### 5. Storage Client (`backend/backups/storage_client.py`)

Updated `read_backup_via_worker()` to accept `is_binary` parameter:

```python
def read_backup_via_worker(
    storage_backend: str,
    storage_ref: str,
    storage_config: Dict[str, Any],
    *,
    task_identifier: Optional[str] = None,
    is_binary: bool = False,  # NEW
    timeout: int = 60,
) -> Dict[str, Any]:
```

**Impact**: API properly communicates backup type to storage workers.

### 6. API Download Endpoint (`backend/api/views.py`)

Enhanced `StoredBackupViewSet.download()` to handle both text and binary:

```python
is_binary = not backup_result.is_text

result = read_backup_via_worker(
    ...,
    is_binary=is_binary,  # NEW
    ...
)

if is_binary:
    # Decode base64 if needed
    binary_data = base64.b64decode(content) if isinstance(content, str) else content
    
    # Return FileResponse with application/octet-stream MIME type
    return FileResponse(
        io.BytesIO(binary_data),
        filename=f"{device.name}_{timestamp}.bin",
        content_type='application/octet-stream'
    )
else:
    # Return text as before
    resp = HttpResponse(content, content_type='text/plain')
    resp['Content-Disposition'] = f'attachment; filename="{device.name}.cfg"'
    return resp
```

**Impact**: 
- Text backups download as `.cfg` files
- Binary backups download as `.bin` files
- Proper MIME types for browser handling

### 7. Frontend UI (`frontend/src/pages/ViewBackups.vue`)

**Table Column** - Added "Type" column showing "Text" or "Binary"

**View Button** - Only shown for text backups:
```vue
<q-btn
  v-if="props.row.status === 'success' && props.row.is_text"
  color="primary"
  icon="visibility"
  label="View"
  @click="viewBackup(props.row)"
/>
```

**Compare Button** - Only enabled if both selected backups are text:
```javascript
const canCompare = computed(() => {
  if (!selectedA.value || !selectedB.value) return false
  const backupA = backups.value.find(b => b.id === selectedA.value)
  const backupB = backups.value.find(b => b.id === selectedB.value)
  return backupA && backupB && backupA.is_text && backupB.is_text
})
```

**Download Button** - Works for both, with different icons/labels:
```vue
<q-btn
  :icon="props.row.is_text ? 'download' : 'cloud_download'"
  :label="props.row.is_text ? 'Download' : 'Download (Binary)'"
  @click="downloadBackup(props.row)"
/>
```

**Download Handler** - Detects backup type and uses appropriate response type:
```javascript
const responseType = backup.is_text ? 'text' : 'blob'
const response = await api.get(`/stored-backups/${backup.id}/download/`, {
  responseType: responseType
})

if (backup.is_text) {
  // Download as .txt
} else {
  // Download as .bin
}
```

**Impact**: 
- Binary backups cannot be viewed inline (not human-readable)
- Binary backups cannot be compared (diff is meaningless)
- Download works for all backups
- Clear visual distinction in UI

### 8. Sample Binary Plugin (`backend/backups/plugins/binary_dummy.py`)

Created demo binary plugin:

```python
PLUGIN = BackupPlugin(
    key='binary_dummy',
    friendly_name='Binary Dummy (Demo)',
    description='Demo binary backup plugin (1MB dummy firmware). For testing binary backup functionality. DO NOT use in production.',
    entrypoint=_generate_binary_backup,
    is_binary=True  # <-- CRITICAL
)
```

**Impact**: 
- Demonstrates binary plugin pattern
- Can be assigned to devices for testing
- Returns base64-encoded 1 MB dummy firmware

### 9. Documentation

Created two comprehensive guides:

1. **`docs/BINARY_BACKUP_SUPPORT.md`** (10 sections)
   - Current architecture analysis
   - Plugin interface changes
   - Data flow diagrams
   - Storage backend updates
   - Collector task changes
   - Data transfer architecture for 250 MB files
   - Recommended approach (base64 encoding)
   - Testing checklist
   - Security considerations
   - Migration path

2. **`docs/BINARY_BACKUP_IMPLEMENTATION.md`** (12 sections)
   - Overview
   - Architecture summary
   - Text backup usage (unchanged)
   - Binary backup creation guide
   - Key requirements for binary plugins
   - Frontend behavior matrix
   - Configuration steps
   - Testing procedures
   - Troubleshooting guide
   - API endpoint reference
   - Production plugin template
   - Next steps and support

---

## Backward Compatibility

✅ **All existing functionality preserved**:
- Text-based plugins work unchanged
- `is_binary` defaults to `False` for existing plugins
- `BackupSerializer` includes `is_text` field (already existed)
- Existing backups unaffected
- No database migrations required

---

## How to Use

### For Text Backups (No Changes)

Text plugins work exactly as before:

```python
PLUGIN = BackupPlugin(
    key='mikrotik_ssh_export',
    friendly_name='Mikrotik SSH Export',
    description='Connects to Mikrotik via SSH',
    entrypoint=_export_config,
    is_binary=False  # or omit (default)
)
```

### For Binary Backups (New)

Create binary plugin:

```python
import base64
from .base import BackupPlugin

def _collect_firmware(config, timeout=None):
    # ... connect to device and get binary data ...
    binary_data = download_firmware(...)
    
    # CRITICAL: return base64-encoded string for JSON transport
    encoded = base64.b64encode(binary_data).decode('ascii')
    
    return {
        'task_id': None,
        'status': 'success',
        'timestamp': datetime.utcnow().isoformat() + 'Z',
        'log': [f'Downloaded {len(binary_data)} bytes'],
        'device_config': encoded  # BASE64 STRING
    }

PLUGIN = BackupPlugin(
    key='firmware_tftp',
    friendly_name='Firmware TFTP',
    description='Download firmware via TFTP',
    entrypoint=_collect_firmware,
    is_binary=True  # <-- CRITICAL
)
```

Then:
1. Copy to `backend/backups/plugins/`
2. Restart Django: `./devicevault.sh restart`
3. Assign to devices in admin
4. Run backups
5. UI automatically handles binary-specific restrictions

---

## Data Transfer Architecture for 250 MB Files

### Chosen Approach: Base64 Encoding

**Rationale**:
- ✅ Simple (no architectural changes)
- ✅ Reliable (standard JSON encoding)
- ✅ Compatible (works with all storage backends)
- ⚠️ 33% size overhead (250 MB → 333 MB, acceptable)
- ⚠️ Memory usage (250 MB loaded once, acceptable)

**Flow**:
```
Plugin collects 250 MB binary
    ↓
Plugin returns base64-encoded 333 MB string
    ↓
Worker publishes to Redis stream
    ↓
Orchestrator reads from Redis (size: 333 MB)
    ↓
Storage decodes base64 and writes 250 MB binary
    ↓
Download decodes from storage, returns 250 MB binary
```

### Alternative Approaches (Not Implemented)

**Streaming Direct to Storage** (Higher complexity, same overhead):
- Plugin returns file handle
- Worker pipes directly to storage
- Avoids base64, but adds storage task complexity
- Workers must know about storage (violates constraint)

**Compression** (Reduces overhead):
- Gzip binary before base64 (~50-80% reduction)
- Could reduce 250 MB to 50-125 MB
- Added CPU cost, complexity

**S3/Cloud Storage** (Future enhancement):
- Stream directly to cloud endpoints
- Avoids local filesystem constraints
- Requires additional configuration

**Current choice prioritizes simplicity and maintainability** over maximum efficiency.

---

## Testing

### Quick Start

1. **Verify plugin discovery**:
   ```bash
   curl -H "Authorization: Token <TOKEN>" \
     http://localhost:8000/api/backup-methods/
   ```
   
   Should see:
   ```json
   {
     "key": "binary_dummy",
     "friendly_name": "Binary Dummy (Demo)",
     "is_binary": true
   }
   ```

2. **Assign to device**:
   - Django admin → Devices → Edit → Backup Method → "Binary Dummy (Demo)" → Save

3. **Trigger backup**:
   - Run scheduled backup or manual trigger

4. **Verify in UI**:
   - View backups → Type column shows "Binary"
   - View button disabled
   - Compare button disabled
   - Download button works, saves as `.bin` file

### Verification Checklist

- [ ] Backup methods API returns `is_binary` flag
- [ ] Binary plugin appears in dropdown when editing device
- [ ] Backup completes with `status: success`
- [ ] Backup record has `is_text: false`
- [ ] View button is disabled for binary backup
- [ ] Compare button is disabled (no two binary selected)
- [ ] Download saves as `.bin` file
- [ ] Binary file downloads correctly (checksum matches original)
- [ ] Text backups still work unchanged
- [ ] Compare works for two text backups

---

## Storage Characteristics

### Filesystem Storage

- **Write**: Binary mode `'wb'`, no encoding
- **Size Limit**: ~16 EB on ext4 (250 MB is trivial)
- **Performance**: Standard I/O (no chunking needed)
- **Example**: `/backups/backup_method=firmware_tftp/device_1/2026-01-13-103000.bin`

### Git Storage

- **Write**: Git binary blob (native support)
- **Size Limit**: Similar to filesystem
- **Performance**: Slower for large files (Git overhead)
- **Example**: Git commit with binary blob at `device_1/firmware.bin`

Both handle 250 MB efficiently without special streaming.

---

## Monitoring & Maintenance

### Storage Space

Binary backups can be large. Monitor:
```bash
du -sh /path/to/backup/storage/
```

Implement retention policies:
- Delete backups older than 30 days (example)
- Keep max 10 most recent per device
- Manual archival to cold storage

### Verification

After backup completes, verify:
```bash
# Check file exists and has size > 0
ls -lh /path/to/backup/storage/backup_method=firmware_tftp/device_*/

# Verify with checksum (if known)
sha256sum /path/to/backup/...
```

---

## Limitations & Future Work

### Current Limitations

1. **No diff for binary** - By design (not human-readable)
2. **No streaming upload** - Uses base64 (33% overhead)
3. **No compression** - Future enhancement
4. **No checksums** - Could add SHA256 verification
5. **No cloud storage** - Only filesystem/Git

### Future Enhancements

1. **Streaming upload** - Pipe device → storage directly
2. **Compression** - Gzip before base64 (50-80% reduction)
3. **Checksums** - SHA256 verification on download
4. **S3 backend** - Stream to AWS S3, Azure Blob, etc.
5. **Binary diff** - For firmware deltas (tool-specific)
6. **Range requests** - HTTP resume capability for large downloads

---

## Code Changes Summary

| File | Change | Impact |
|------|--------|--------|
| `backend/backups/plugins/base.py` | Added `is_binary` field | Plugin metadata now includes binary flag |
| `backend/api/views.py` | Expose `is_binary` in API | Frontend knows about binary plugins |
| `backend/storage/fs.py` | Handle binary mode | Filesystem storage supports binary |
| `backend/storage/git.py` | Handle binary mode | Git storage supports binary |
| `backend/devicevault_worker.py` | Propagate `is_binary` in Redis | Orchestrator can detect binary |
| `backend/backups/storage_client.py` | Accept `is_binary` param | Storage client communicates type |
| `backend/api/views.py` (download) | Return FileResponse for binary | API returns binary files correctly |
| `frontend/src/pages/ViewBackups.vue` | Conditional buttons & type column | UI respects binary constraints |
| `backend/backups/plugins/binary_dummy.py` | NEW plugin | Demo binary backup |
| `docs/BINARY_BACKUP_SUPPORT.md` | NEW documentation | Architectural analysis |
| `docs/BINARY_BACKUP_IMPLEMENTATION.md` | NEW documentation | Implementation guide |

---

## Questions?

See `docs/BINARY_BACKUP_SUPPORT.md` for architectural details or `docs/BINARY_BACKUP_IMPLEMENTATION.md` for usage guidance.

