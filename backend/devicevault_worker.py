
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
