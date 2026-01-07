"""
DeviceVault - A comprehensive network device backup management application with web interface for user and admin access and backend component for automated backup collection.
Copyright (C) 2026, Slinky Software

This program is free software: you can redistribute it and/or modify
it under the terms of the GNU General Public License as published by
the Free Software Foundation, either version 3 of the License, or
(at your option) any later version.

This program is distributed in the hope that it will be useful,
but WITHOUT ANY WARRANTY; without even the implied warranty of
MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
GNU General Public License for more details.

You should have received a copy of the GNU General Public License
along with this program.  If not, see <http://www.gnu.org/licenses/>.
"""

import os
from apscheduler.schedulers.background import BackgroundScheduler
from django.core.wsgi import get_wsgi_application
os.environ.setdefault('DJANGO_SETTINGS_MODULE','devicevault.settings')
application = get_wsgi_application()
from devices.models import Device
from backups.models import Backup
from storage.fs import FileSystemStorage
from backups.plugins import get_plugin

def run_backup(device):
    plugin = get_plugin(device.backup_method)
    if not plugin:
        print(f"Unknown backup method for device {device.name}: {device.backup_method}")
        return
    
    cred = device.credential
    if not cred:
        print(f"No credentials configured for device {device.name}")
        return
    
    try:
        content = plugin.run(device.ip_address, cred.data)
        storage = FileSystemStorage(base_path=os.environ.get('DEVICEVAULT_BACKUPS','backups'))
        # Use backup method instead of manufacturer in path
        rel_path = f"{device.name}/{device.backup_method}/{device.device_type.name}/{device.id}.cfg"
        saved = storage.save(rel_path, content)
        Backup.objects.create(
            device=device, 
            location=device.backup_location, 
            status='success', 
            artifact_path=saved, 
            size_bytes=len(content)
        )
        print(f"Backup successful for {device.name}")
    except Exception as e:
        print(f"Backup failed for {device.name}: {e}")
        Backup.objects.create(
            device=device,
            location=device.backup_location,
            status='failed',
            artifact_path='',
            size_bytes=0
        )

scheduler = BackgroundScheduler()

def schedule():
    for d in Device.objects.filter(enabled=True):
        scheduler.add_job(run_backup, 'interval', args=[d], hours=24, id=f"dev_{d.id}", replace_existing=True)
    scheduler.start()

if __name__=='__main__': schedule()
