# Binary Configuration Backup Support

## Executive Summary

This document outlines the architecture and implementation plan for extending DeviceVault to support binary configuration backups alongside the existing text-based approach. Binary backups will be transferred, stored, and downloadable, but without in-browser viewing or diff capabilities.

---

## 1. Current Architecture Analysis

### 1.1 Data Flow

```
Device → Collector Plugin → Celery Worker → Storage Backend → API → Frontend
   ↓              ↓                 ↓             ↓           ↓       ↓
 Config       device_config    device_config   file/blob   JSON   View/Diff
```

### 1.2 Key Components

#### Plugin System (`backend/backups/plugins/`)
- **Base Interface**: `BackupPlugin` dataclass with metadata and entrypoint
- **Entrypoint Signature**: `(config: Dict, timeout: Optional[int]) -> Dict[str, Any]`
- **Return Contract**: JSON dict with `device_config` (currently assumed string)
- **Discovery**: Automatic via `__init__.py` module scanning

#### Collector Task (`backend/devicevault_worker.py`)
- **Task**: `device_collect_task(config_json: str) -> dict`
- **Responsibility**: Execute plugin, publish result to Redis stream
- **Assumption**: `device_config` is text (JSON serialization)
- **Constraint**: Does NOT know about storage backend (that's orchestrator's job)

#### Storage Layer (`backend/storage/fs.py`, `git.py`)
- **Functions**: `store_backup(content: str, rel_path: str, config: Dict) -> str`
- **Assumption**: Content is text (write mode: 'w', encoding='utf-8')
- **Return**: `storage_ref` (path identifier for later retrieval)

#### API Endpoints (`backend/api/views.py`)
- **Download Endpoint**: `/api/stored-backups/{pk}/download/`
- **Behavior**: Calls `read_backup_via_worker()` → returns JSON with `content`
- **Frontend**: Displays text inline, enables diff operations

#### Frontend (`frontend/src/pages/ViewBackups.vue`, `CompareBackups.vue`)
- **View Button**: Loads content via download endpoint, displays as text
- **Compare Button**: Diff algorithm on text lines
- **Binary Constraint**: Both are text-only operations

### 1.3 Data Type Flow Path

```
Plugin.device_config (currently: str)
       ↓
Worker publishes to Redis Stream (JSON serializable)
       ↓
Orchestrator consumes, calls storage.store_backup()
       ↓
Storage writes with encoding='utf-8'
       ↓
API download endpoint reads, returns as string in JSON
       ↓
Frontend displays inline or runs diff
```

---

## 2. Proposed Changes

### 2.1 Plugin Interface Enhancement

**File**: `backend/backups/plugins/base.py`

Add `is_binary` flag to `BackupPlugin`:

```python
@dataclass
class BackupPlugin:
    key: str
    friendly_name: str
    description: str
    entrypoint: CollectorCallable
    is_binary: bool = False  # NEW: True for binary, False for text
```

**Why**: Hard-coded per plugin (e.g., "mikrotik_ssh_export" is text, "firmware_binary_export" is binary).

**Contract Update**:
- **Text plugins** return `device_config` as string (existing behavior)
- **Binary plugins** return `device_config` as **base64-encoded string** (JSON serializable)
- Orchestrator detects `is_binary` from plugin metadata and decodes before storage

---

### 2.2 Backup Model Update

**File**: `backend/backups/models.py`

Already has the field:
```python
is_text = models.BooleanField(default=True, help_text='True if text artifact (configs), False if binary')
```

**No changes needed** — field exists but not currently used. Will now be populated from plugin's `is_binary` flag.

---

### 2.3 Storage Backend Updates

#### 2.3.1 Filesystem Storage (`backend/storage/fs.py`)

**Challenge**: Current implementation uses text mode ('w', encoding='utf-8'). Binary data must use binary mode ('wb').

**Solution**: Detect data type and write accordingly:

```python
def store_backup(content: str | bytes, rel_path: str, config: Dict, is_binary: bool = False) -> str:
    """
    Args:
        content: str (text) or bytes (binary, base64-decoded from plugin)
        rel_path: Relative path under configured base directory
        config: Storage configuration
        is_binary: True if content is binary, False if text
    
    Returns:
        storage_ref: Path identifier
    """
    base_path = config.get('base_path') or config.get('path')
    os.makedirs(base_path, exist_ok=True)
    full_path = os.path.join(base_path, rel_path)
    os.makedirs(os.path.dirname(full_path), exist_ok=True)
    
    if is_binary:
        # Binary write
        with open(full_path, 'wb') as f:
            f.write(content if isinstance(content, bytes) else content.encode('latin-1'))
    else:
        # Text write (existing)
        with open(full_path, 'w', encoding='utf-8') as f:
            f.write(content)
    
    return rel_path
```

**Supports**: Files up to filesystem limits (typically 16 EB on ext4). For 250 MB files, this is trivial.

#### 2.3.2 Git Storage (`backend/storage/git.py`)

Similar logic: detect `is_binary` and handle accordingly. Git can store binary blobs natively.

**Key Concern**: Very large binary files (250 MB) may slow Git operations. Consider:
- Shallow clones or sparse checkouts for retrieval
- Or defer binary storage to pure filesystem backend

#### 2.3.3 Retrieval Functions

```python
def read_backup(storage_ref: str, config: Dict, is_binary: bool = False) -> str | bytes:
    """
    Returns:
        str (text, UTF-8 decoded) or bytes (binary) depending on is_binary flag
    """
    ...
```

---

### 2.4 Collector Task (`backend/devicevault_worker.py`)

**Key Principle**: Worker MUST NOT know about storage backend or `is_binary` state. Worker only knows about plugins.

**Changes**:

1. **Plugin Result Handling**: Accept `device_config` as string (text or base64-encoded)
2. **Result Publishing**: Include plugin's `is_binary` flag in Redis stream payload
3. **No Storage Calls**: Worker does NOT call `store_backup()` (orchestrator does)

```python
# In device_collect_task:
plugin = get_plugin(plugin_key)
result = plugin.run(plugin_cfg, timeout=timeout)

# Publish to Redis Stream
payload = {
    'task_id': tid or '',
    'task_identifier': task_identifier,
    'device_id': str(device_id),
    'status': result.get('status'),
    'device_config': result.get('device_config') or '',
    'is_binary': str(plugin.is_binary),  # NEW: propagate plugin's binary flag
    'collection_duration_ms': str(collection_duration_ms),
    ...
}
redis_client.xadd(RESULTS_STREAM, payload)
```

---

### 2.5 Orchestrator (Assumed Django View/Management Command)

The component that consumes Redis stream and calls storage:

**Pseudo-code**:
```python
# Orchestrator loop
message = redis_stream.read()
plugin = get_plugin(message['backup_method'])

if message['status'] == 'success':
    device_config = message['device_config']
    
    # Decode if binary
    if plugin.is_binary:
        device_config = base64.b64decode(device_config)
    
    # Call storage (now aware of binary type)
    storage_ref = store_backup(
        content=device_config,
        rel_path=...,
        config=...,
        is_binary=plugin.is_binary
    )
    
    # Create Backup record with is_text flag
    Backup.objects.create(
        device=device,
        location=location,
        status='success',
        artifact_path=storage_ref,
        is_text=not plugin.is_binary,  # NEW
        ...
    )
```

**Critical**: Orchestrator MUST NOT be part of the worker. It is a separate process/service that:
- Consumes from Redis stream
- Knows about storage backends
- Persists records to database
- Enforces retention policies

---

### 2.6 Backup Model and Serializers

**File**: `backend/backups/models.py`

Field already exists:
```python
is_text = models.BooleanField(default=True, help_text='...')
```

**Serializer Update**: Expose `is_text` in `BackupSerializer` and API response.

**Frontend Consumption**: Check `is_text` flag to conditionally enable/disable view and compare.

---

### 2.7 API Download Endpoint

**File**: `backend/api/views.py`

Current: `/api/stored-backups/{pk}/download/` returns JSON with `content` field (text).

**Changes**:

```python
@decorators.action(detail=True, methods=['get'])
def download(self, request, pk=None):
    """Download backup content (text or binary)."""
    backup_result = self.get_object()
    
    # ... authorization checks ...
    
    storage_record = StoredBackup.objects.filter(...).first()
    
    # Check if binary
    is_binary = not backup_result.is_text
    
    try:
        result = read_backup_via_worker(
            storage_backend=storage_record.storage_backend,
            storage_ref=storage_record.storage_ref,
            storage_config=location.config,
            is_binary=is_binary,  # NEW: inform storage layer
            task_identifier=f'read:{storage_record.task_identifier}'
        )
        
        if is_binary:
            # Return binary file download (FileResponse)
            # Decode if base64 encoded during transfer
            content = base64.b64decode(result['content']) if isinstance(result['content'], str) else result['content']
            return FileResponse(
                io.BytesIO(content),
                filename=f"{backup_result.device.name}_{backup_result.timestamp.isoformat()}.bin",
                content_type='application/octet-stream'
            )
        else:
            # Return JSON with text content (existing)
            return response.Response({'content': result['content']}, status=status.HTTP_200_OK)
    except Exception as exc:
        return response.Response({'error': str(exc)}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)
```

---

### 2.8 Frontend Changes

**Files**:
- `frontend/src/pages/ViewBackups.vue`
- `frontend/src/pages/CompareBackups.vue`

**Logic**:

```javascript
// In ViewBackups.vue template:
<q-btn
  v-if="props.row.status === 'success' && props.row.is_text"  // BINARY CHECK
  color="primary"
  icon="visibility"
  label="View"
  @click="viewBackup(props.row)"
/>

<q-btn
  v-if="props.row.status === 'success'"
  color="primary"
  :icon="props.row.is_text ? 'download' : 'cloud_download'"
  :label="props.row.is_text ? 'Download' : 'Download (Binary)'"
  @click="downloadBackup(props.row)"
/>

// In data table columns:
{
  name: 'is_text',
  label: 'Type',
  field: 'is_text',
  format: val => val ? 'Text' : 'Binary'
}
```

**Download Handler**:

```javascript
async downloadBackup(backup) {
  try {
    const response = await api.get(`/stored-backups/${backup.id}/download/`, {
      responseType: backup.is_text ? 'json' : 'blob'
    })
    
    if (backup.is_text) {
      // Text: you can view inline or download
      const text = response.data.content
      // ... handle text download ...
    } else {
      // Binary: force download
      const url = window.URL.createObjectURL(response.data)
      const a = document.createElement('a')
      a.href = url
      a.download = `${backup.device.name}_${backup.timestamp}.bin`
      a.click()
    }
  } catch (err) {
    this.$q.notify({type: 'negative', message: 'Download failed: ' + err.message})
  }
}
```

**Compare Button**: Only show if both selected backups are `is_text === true`.

---

## 3. Data Transfer Architecture for Large Files (250 MB)

### 3.1 Current Data Flow Issues

**Problem**: Binary data must be JSON-serializable when passed through Redis streams and HTTP APIs.

**Current Approach (Plugin Result)**:
```
Plugin returns device_config as string
  ↓
Worker publishes to Redis (JSON serialization)
  ↓
Orchestrator reads from Redis
```

**Issue**: Base64 encoding increases size by ~33%.
- 250 MB binary → ~333 MB base64 string → stress on Redis, network, JSON parsers

### 3.2 Recommended Solutions (In Priority Order)

#### Solution A: Stream Binary Directly to Storage (Recommended)

**Pattern**:
1. Plugin implements a streaming interface: returns file handle/stream, not full content
2. Worker pipes plugin output directly to storage backend
3. Storage backend accepts both strings and file-like objects
4. Binary data never touches Redis or HTTP JSON layer

**Benefits**:
- ✅ No base64 bloat
- ✅ Handles 250 MB efficiently (streaming chunks)
- ✅ Worker stays stateless (can delegate storage to worker task if needed)
- ✅ Minimal memory usage

**Implementation**:

```python
# In plugins/base.py:
# Extend return contract:
# {
#   "device_config": <str | file-like | bytes>,
#   "is_binary": bool,
#   "stream_mode": bool (if true, device_config is file-like)
# }

# In storage/fs.py:
def store_backup(content, rel_path, config, is_binary=False, stream_mode=False):
    if stream_mode:
        # Streaming write: read from file-like in chunks
        with open(full_path, 'wb') as f_out:
            while chunk := content.read(1024*1024):  # 1 MB chunks
                f_out.write(chunk)
    else:
        # Existing logic for string/bytes
        ...
```

**Worker Change**: 
```python
# If result indicates stream_mode, worker doesn't serialize to Redis
# Instead, worker calls storage directly as a side-effect
# (breaking the worker/storage separation, but justified for binary)
# OR: worker publishes "content_uri" instead of full config
```

#### Solution B: Chunked Upload via Storage Worker Task

**Pattern**:
1. Collector returns only metadata (filename, checksum, size)
2. Collector also returns file handle/stream
3. Storage worker task receives file-like object and metadata
4. Storage worker writes directly, returns storage_ref

**Benefits**:
- ✅ Maintains worker/storage separation
- ✅ Handles streaming naturally
- ✅ Storage worker can be scaled independently

**Implementation**: Requires refactoring collector task result contract.

#### Solution C: Temporary File Handoff

**Pattern**:
1. Plugin writes binary to temporary file in shared volume
2. Plugin returns file path instead of content
3. Orchestrator reads from file, stores permanently
4. Temporary file is cleaned up

**Benefits**:
- ✅ Simple to implement
- ✅ No base64 encoding

**Drawbacks**:
- ❌ Requires shared filesystem
- ❌ Temporary file cleanup complexity
- ❌ Not suitable for distributed deployments

#### Solution D: Compress Binary, Then Base64

**Pattern**:
1. Binary data → compress (gzip) → base64
2. Worker publishes compressed base64
3. Orchestrator decodes and stores

**Benefits**:
- Reduces size by 50-80% (typical for firmware)
- Existing JSON transport works

**Drawbacks**:
- Still ~150 MB for typical firmware
- Decompress overhead

---

### 3.3 Recommended Approach for DeviceVault

**Adopt Solution A + B Hybrid**:

1. **For Text Backups** (existing):
   - Plugin returns `device_config` as string
   - Worker publishes to Redis
   - Orchestrator consumes and stores

2. **For Binary Backups** (new):
   - Plugin accepts optional `stream_output_path` parameter in config
   - Plugin writes binary directly to path within worker container
   - Plugin returns metadata: `{device_config: "<path>", stream_mode: true}`
   - Worker preserves the file (or mounts it in shared storage)
   - Storage task receives file handle and writes to permanent storage
   - Temporary file is cleaned up after storage completes

**Alternatively** (simpler, less architectural change):

1. Plugin returns device_config as base64 string (like text, but encoded)
2. Include `is_binary: true` flag
3. Worker publishes normally to Redis
4. Orchestrator detects binary, decodes base64, stores as binary
5. Accept the ~33% overhead (250 MB → 333 MB) as acceptable for operational simplicity

**Justification**:
- Redis can handle 333 MB messages (default limit is 500 MB)
- Network transfer is fast (minor compared to collection time)
- Simplicity: no schema changes to result contract, no file handoff complexity
- Workers remain stateless and orchestrator-agnostic

---

## 4. Implementation Order

1. **Plugin Interface** → Add `is_binary` flag to `BackupPlugin`
2. **Storage Layer** → Handle both text and binary (mode detection)
3. **Backup Model** → Ensure `is_text` field is used (already exists)
4. **Worker** → Propagate `is_binary` flag in Redis stream
5. **API Serializers** → Expose `is_text` in responses
6. **API Download** → Handle binary file responses
7. **Frontend** → Disable view/compare for binary
8. **Sample Plugin** → Create binary plugin example

---

## 5. Security Considerations

### 5.1 Binary File Validation

- **Problem**: Accepting arbitrary binary uploads could introduce malware
- **Recommendation**: 
  - Store all backups with restricted permissions (readable only by authenticated users via API)
  - Add optional file type validation (e.g., only .bin, .rom files for firmware)
  - Consider integrating with YARA/VirusTotal for suspicious files (optional)

### 5.2 Large File DoS

- **Problem**: Accepting 250 MB binary could be exploited for storage exhaustion
- **Recommendation**:
  - Enforce per-device storage quota
  - Implement retention policies (already exist)
  - Rate-limit backup collection per device

---

## 6. Future Enhancements

1. **Streaming Download for Large Files**: Implement HTTP range requests for resume capability
2. **Compression**: Automatically compress binary on storage
3. **Encryption**: Encrypt binary at rest (if not already)
4. **Binary Diff**: For certain formats (e.g., firmware deltas), implement binary diff algorithms
5. **S3/Cloud Storage**: Extend storage backends to handle streaming uploads to cloud
6. **Checksums**: Store SHA256 of binary for integrity verification

---

## 7. Migration Path

### For Existing Installations

No breaking changes. All existing text plugins continue to work:
- `is_binary` defaults to `False` in `BackupPlugin`
- `is_text` defaults to `True` in `Backup` model
- API responses include `is_text` field (no change to existing clients)

### For New Binary Plugins

1. Create plugin module in `backend/backups/plugins/`
2. Set `is_binary=True` in `PLUGIN` definition
3. Ensure `device_config` is base64-encoded string (or use streaming mode)
4. Restart Django
5. Plugin appears in backup methods list
6. Assign to devices; backups work automatically with UI restrictions

---

## 8. Example Binary Plugin

```python
# backend/backups/plugins/firmware_binary.py

from typing import Dict, Any, Optional
from .base import BackupPlugin
import base64

def _fetch_firmware(config: Dict[str, Any], timeout: Optional[int] = None) -> Dict[str, Any]:
    """Example: Fetch firmware binary from device via TFTP/SCP."""
    ip = config.get('ip')
    creds = config.get('credentials', {})
    
    try:
        # Pseudo-code: connect to device, download firmware
        binary_data = fetch_binary_from_device(ip, creds, timeout)
        
        # Return as base64 for JSON transport
        encoded = base64.b64encode(binary_data).decode('ascii')
        
        return {
            'task_id': None,
            'status': 'success',
            'timestamp': datetime.utcnow().isoformat() + 'Z',
            'log': [f'Downloaded {len(binary_data)} bytes'],
            'device_config': encoded  # BASE64 STRING
        }
    except Exception as exc:
        return {
            'task_id': None,
            'status': 'failure',
            'timestamp': datetime.utcnow().isoformat() + 'Z',
            'log': [f'Error: {exc}'],
            'device_config': None
        }

PLUGIN = BackupPlugin(
    key='firmware_binary_export',
    friendly_name='Firmware Binary Export',
    description='Downloads device firmware as binary blob via TFTP.',
    entrypoint=_fetch_firmware,
    is_binary=True  # <-- CRITICAL: Mark as binary
)
```

---

## 9. Testing Checklist

- [ ] Binary plugin returns base64-encoded string
- [ ] Worker publishes `is_binary=true` to Redis stream
- [ ] Orchestrator decodes and stores as binary (not UTF-8 text mode)
- [ ] Backup model has `is_text=false` for binary backups
- [ ] API download returns correct MIME type and headers for binary
- [ ] Frontend: View button disabled for binary backups
- [ ] Frontend: Compare button disabled for binary backups
- [ ] Frontend: Download works for both text and binary
- [ ] Storage backend read returns bytes (not decoded string) for binary
- [ ] 250 MB binary file transfers successfully end-to-end

---

## 10. Conclusion

Binary backup support is achievable with minimal architectural changes:

1. **Plugin System**: Add `is_binary` metadata flag (1 field)
2. **Storage Layer**: Handle both text and binary modes (mode detection)
3. **Data Transfer**: Use base64 encoding for JSON transport (accepted overhead)
4. **Worker Constraint**: No changes to worker/orchestrator separation
5. **Frontend**: Conditional UI logic based on `is_text` flag
6. **Scalability**: Handles 250 MB files via existing infrastructure

The approach maintains backward compatibility, keeps workers stateless, and provides clear separation of concerns between collection, storage, and presentation layers.
