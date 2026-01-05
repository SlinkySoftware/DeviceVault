
import os
from apscheduler.schedulers.background import BackgroundScheduler
from django.core.wsgi import get_wsgi_application
os.environ.setdefault('DJANGO_SETTINGS_MODULE','devicevault.settings')
application = get_wsgi_application()
from devices.models import Device
from backups.models import Backup
from storage.fs import FileSystemStorage
from connectors.ssh import SSHConnector

def run_backup(device):
    cred = device.credential
    content = SSHConnector().fetch_config(device, cred)
    storage = FileSystemStorage(base_path=os.environ.get('DEVICEVAULT_BACKUPS','backups'))
    rel_path = f"{device.name}/{device.manufacturer.name}/{device.device_type.name}/{device.id}.cfg"
    saved = storage.save(rel_path, content)
    Backup.objects.create(device=device, location=device.backup_location, status='success', artifact_path=saved, size_bytes=len(content))

scheduler = BackgroundScheduler()

def schedule():
    for d in Device.objects.filter(enabled=True):
        scheduler.add_job(run_backup, 'interval', args=[d], hours=24, id=f"dev_{d.id}", replace_existing=True)
    scheduler.start()

if __name__=='__main__': schedule()
