# Backup Methods Plugin System

DeviceVault implements a plugin-based architecture for backup methods, allowing flexible addition of new device types without modifying core application code.

## Architecture

### Plugin System Overview

Backup method plugins are Python modules located under `backend/backups/plugins/`. Each plugin:

1. **Implements a single entry point** - A callable function accepting IP address and credentials
2. **Returns the configuration** - As a string that will be passed to the storage layer
3. **Exposes metadata** - Friendly name and description for frontend display
4. **Is automatically discovered** - No manual registration required

### Plugin Interface

Each plugin module must expose a `PLUGIN` variable containing a `BackupPlugin` instance:

```python
from backups.plugins.base import BackupPlugin

def backup_function(ip_address: str, credentials: dict) -> str:
    # Custom logic to connect and retrieve config
    # credentials contains: {'username': '...', 'password': '...'}
    return configuration_text

PLUGIN = BackupPlugin(
    key='unique_plugin_key',
    friendly_name='Human Readable Name',
    description='What this plugin does and what devices it supports',
    entrypoint=backup_function
)
```

### Plugin Discovery

- Plugins are auto-discovered from `backend/backups/plugins/` at runtime
- Module names starting with `_` are ignored
- Plugins are cached after first discovery
- Invalid plugins are logged and skipped

## Available Plugins

### Mikrotik SSH Export

**Key:** `mikrotik_ssh_export`  
**Module:** `backend/backups/plugins/mikrotik_ssh.py`

Connects to Mikrotik RouterOS devices via SSH and executes `/export show-sensitive` to capture the full configuration including sensitive data.

**Requirements:**
- SSH access enabled on device
- Valid username/password credentials
- RouterOS 6.x or 7.x

**Example Configuration:**
```python
# Device setup
device.backup_method = 'mikrotik_ssh_export'
device.credential = <credential with username/password>
```

### No Operation (noop)

**Key:** `noop`  
**Module:** `backend/backups/plugins/noop.py`

A placeholder plugin that returns empty content. Used for:
- Demo/example devices that shouldn't be backed up
- Devices in testing that aren't yet ready for backup
- Seed data initialization

## Device Configuration

### Assigning Backup Methods

Each device has a `backup_method` field that stores the plugin key:

```python
from devices.models import Device
from credentials.models import Credential

device = Device.objects.get(name='Router-01')
device.backup_method = 'mikrotik_ssh_export'
device.credential = Credential.objects.get(name='Mikrotik Admin')
device.save()
```

### Frontend UI

The **Backup Methods** admin page (`/vaultadmin/backup-methods`) displays all discovered plugins with:
- Friendly name
- Description
- Read-only list (plugins cannot be added/removed via UI)

When editing a device, the backup method is selected from a dropdown showing the friendly names of all available plugins.

## Creating New Plugins

### Step 1: Create Plugin Module

Create a new file in `backend/backups/plugins/`, e.g., `cisco_ssh.py`:

```python
"""Cisco IOS/IOS-XE backup via SSH."""

from typing import Dict
import paramiko
from .base import BackupPlugin

def _backup_cisco(ip_address: str, credentials: Dict) -> str:
    """Connect via SSH and run 'show running-config'."""
    username = credentials.get('username')
    password = credentials.get('password')
    
    if not username or not password:
        raise ValueError('Cisco SSH plugin requires username and password')
    
    client = paramiko.SSHClient()
    client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    
    try:
        client.connect(
            hostname=ip_address,
            username=username,
            password=password,
            look_for_keys=False,
            timeout=10
        )
        
        # Cisco specific: disable paging
        client.exec_command('terminal length 0')
        
        _, stdout, stderr = client.exec_command('show running-config')
        output = stdout.read().decode('utf-8', errors='ignore')
        
        if stderr.read():
            raise RuntimeError('Error executing show running-config')
            
        return output
    finally:
        client.close()

PLUGIN = BackupPlugin(
    key='cisco_ssh',
    friendly_name='Cisco IOS SSH',
    description='Connects to Cisco IOS/IOS-XE via SSH and runs show running-config',
    entrypoint=_backup_cisco
)
```

### Step 2: Test Plugin

```python
# backend/manage.py shell
from backups.plugins import get_plugin

plugin = get_plugin('cisco_ssh')
print(plugin.friendly_name)
print(plugin.description)

# Test execution
result = plugin.run('192.168.1.1', {'username': 'admin', 'password': 'secret'})
print(len(result))  # Should show config length
```

### Step 3: Restart Application

Django must be restarted to discover new plugins:

```bash
./devicevault.sh restart
```

The new plugin will appear in the Backup Methods admin page and device edit form.

## Plugin Best Practices

### Error Handling

Always handle connection failures gracefully:

```python
def _backup_device(ip_address: str, credentials: Dict) -> str:
    try:
        # Connection and backup logic
        return config
    except ConnectionError as e:
        raise RuntimeError(f'Failed to connect to {ip_address}: {e}')
    except Exception as e:
        raise RuntimeError(f'Backup failed: {e}')
```

### Credential Validation

Validate required credential fields early:

```python
def _backup_device(ip_address: str, credentials: Dict) -> str:
    required = ['username', 'password']
    missing = [k for k in required if not credentials.get(k)]
    if missing:
        raise ValueError(f'Missing required credentials: {", ".join(missing)}')
    
    # Proceed with backup
```

### Connection Cleanup

Always clean up connections, even on error:

```python
client = SSHClient()
try:
    client.connect(...)
    return client.exec_command('...')
finally:
    client.close()
```

### Timeout Configuration

Set reasonable timeouts for connection and command execution:

```python
client.connect(hostname=ip_address, timeout=10)  # 10 second connect timeout
channel = client.exec_command('...')
channel.settimeout(60)  # 60 second command timeout
```

## Integration with Scheduler

The backup scheduler (`devicevault_worker.py`) uses plugins to perform backups:

```python
from backups.plugins import get_plugin
from devices.models import Device

device = Device.objects.get(id=1)
plugin = get_plugin(device.backup_method)

if plugin:
    config = plugin.run(device.ip_address, device.credential.data)
    # Store config using storage plugin
else:
    print(f'Unknown backup method: {device.backup_method}')
```

## Migration from Manufacturer Field

Previous versions used a `manufacturer` field to identify device types. This has been replaced with the `backup_method` plugin system:

**Before:**
- Device had `manufacturer` ForeignKey (Cisco, Fortigate, etc.)
- Backup logic was hardcoded based on manufacturer

**After:**
- Device has `backup_method` CharField (plugin key)
- Manufacturer is now optional/informational
- Backup logic is plugin-based and extensible

### Migration Notes

The migration `0008_device_backup_method_optional_manufacturer.py`:
1. Adds `backup_method` field with default='noop'
2. Makes `manufacturer` nullable (optional)
3. All existing devices get `backup_method='noop'` by default

## Troubleshooting

### Plugin Not Discovered

1. Check module name doesn't start with `_`
2. Verify `PLUGIN` variable is defined
3. Check backend logs for import errors
4. Restart Django application

### Plugin Shows in UI but Fails to Execute

1. Check credentials are properly formatted
2. Verify network connectivity to device
3. Enable debug logging to see connection details
4. Test plugin directly in Django shell

### Backup Method Not Showing in Dropdown

1. Restart Django application
2. Clear browser cache
3. Check API endpoint: `GET /api/backup-methods/`

## Related Documentation

- [README.md](README.md) - Main application documentation
- [DEVICE_GROUP_RBAC.md](DEVICE_GROUP_RBAC.md) - Device access control
- Backend code: `backend/backups/plugins/`
- Frontend page: `frontend/src/pages/BackupMethods.vue`
