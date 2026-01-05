#!/usr/bin/env python
"""
DeviceVault Data Seeder
Creates sample data for testing and demonstration
"""

import os
import sys
import django

# Setup Django
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'devicevault.settings')
django.setup()

from devices.models import DeviceType, Manufacturer, Device
from credentials.models import CredentialType, Credential
from locations.models import BackupLocation
from policies.models import RetentionPolicy
from core.models import Label
from rbac.models import Permission, Role
from django.contrib.auth.models import User

def create_sample_data():
    print("Creating sample data...")
    
    # Device Types
    device_types = ['Router', 'Switch', 'Firewall', 'Access Point', 'Load Balancer']
    for dt in device_types:
        DeviceType.objects.get_or_create(name=dt)
    print(f"✓ Created {len(device_types)} device types")
    
    # Manufacturers
    manufacturers = ['Cisco', 'Fortigate', 'Dell', 'Sophos', 'Mikrotik', 'Aruba', 'Juniper', 'Palo Alto']
    for mfg in manufacturers:
        Manufacturer.objects.get_or_create(name=mfg)
    print(f"✓ Created {len(manufacturers)} manufacturers")
    
    # Credential Types
    cred_types = ['Local', 'CyberArk', 'HashiCorp Vault', 'Azure Key Vault']
    for ct in cred_types:
        CredentialType.objects.get_or_create(name=ct)
    print(f"✓ Created {len(cred_types)} credential types")
    
    # Sample Credentials
    local_type = CredentialType.objects.get(name='Local')
    credentials = [
        ('Default SSH', {'username': 'admin', 'password': 'changeme'}),
        ('Network Admin', {'username': 'netadmin', 'password': 'secure123'}),
        ('Read Only', {'username': 'readonly', 'password': 'readonly'}),
    ]
    for name, data in credentials:
        Credential.objects.get_or_create(
            name=name,
            defaults={'credential_type': local_type, 'data': data}
        )
    print(f"✓ Created {len(credentials)} credentials")
    
    # Backup Locations
    locations = [
        ('Primary Git', 'git', {'url': 'https://github.com/company/backups.git', 'branch': 'main'}),
        ('Local Storage', 'filesystem', {'path': '/var/backups/devicevault'}),
        ('S3 Bucket', 's3', {'bucket': 'devicevault-backups', 'region': 'us-east-1'}),
    ]
    for name, loc_type, config in locations:
        BackupLocation.objects.get_or_create(
            name=name,
            defaults={'location_type': loc_type, 'config': config}
        )
    print(f"✓ Created {len(locations)} backup locations")
    
    # Retention Policies
    policies = [
        ('Keep Last 30', 30, 30, None),
        ('Keep Last 90', 90, 90, None),
        ('Keep Last 10', 10, None, None),
        ('Keep 1 Year', None, 365, None),
    ]
    for name, max_backups, max_days, max_size in policies:
        RetentionPolicy.objects.get_or_create(
            name=name,
            defaults={
                'max_backups': max_backups,
                'max_days': max_days,
                'max_size_bytes': max_size
            }
        )
    print(f"✓ Created {len(policies)} retention policies")
    
    # Labels
    labels = ['Production', 'Development', 'DMZ', 'Internal', 'Critical', 'Non-Critical']
    for label in labels:
        Label.objects.get_or_create(name=label)
    print(f"✓ Created {len(labels)} labels")
    
    # Permissions
    permissions = [
        ('view_devices', 'Can view devices'),
        ('edit_devices', 'Can edit devices'),
        ('delete_devices', 'Can delete devices'),
        ('view_backups', 'Can view backups'),
        ('manage_credentials', 'Can manage credentials'),
        ('admin_access', 'Full admin access'),
    ]
    for code, desc in permissions:
        Permission.objects.get_or_create(code=code, defaults={'description': desc})
    print(f"✓ Created {len(permissions)} permissions")
    
    # Roles
    admin_role, _ = Role.objects.get_or_create(name='Administrator')
    admin_role.permissions.set(Permission.objects.all())
    admin_role.labels.set(Label.objects.all())
    
    operator_role, _ = Role.objects.get_or_create(name='Operator')
    operator_perms = Permission.objects.filter(code__in=['view_devices', 'view_backups'])
    operator_role.permissions.set(operator_perms)
    
    print("✓ Created roles")
    
    # Sample Devices (only if we have required data)
    if DeviceType.objects.exists() and Manufacturer.objects.exists():
        router_type = DeviceType.objects.get(name='Router')
        switch_type = DeviceType.objects.get(name='Switch')
        firewall_type = DeviceType.objects.get(name='Firewall')
        
        cisco = Manufacturer.objects.get(name='Cisco')
        dell = Manufacturer.objects.get(name='Dell')
        fortigate = Manufacturer.objects.get(name='Fortigate')
        
        default_cred = Credential.objects.first()
        default_location = BackupLocation.objects.first()
        default_policy = RetentionPolicy.objects.first()
        
        sample_devices = [
            ('Core-Router-01', '192.168.1.1', 'core-router-01.local', router_type, cisco),
            ('Core-Router-02', '192.168.1.2', 'core-router-02.local', router_type, cisco),
            ('Core-Switch-01', '192.168.1.10', 'core-switch-01.local', switch_type, dell),
            ('Core-Switch-02', '192.168.1.11', 'core-switch-02.local', switch_type, dell),
            ('Edge-Firewall-01', '192.168.1.254', 'firewall-01.local', firewall_type, fortigate),
        ]
        
        for name, ip, dns, dtype, mfg in sample_devices:
            device, created = Device.objects.get_or_create(
                name=name,
                defaults={
                    'ip_address': ip,
                    'dns_name': dns,
                    'device_type': dtype,
                    'manufacturer': mfg,
                    'credential': default_cred,
                    'backup_location': default_location,
                    'retention_policy': default_policy,
                    'enabled': True
                }
            )
            if created:
                # Add some labels
                prod_label = Label.objects.get(name='Production')
                critical_label = Label.objects.get(name='Critical')
                device.labels.add(prod_label, critical_label)
        
        print(f"✓ Created {len(sample_devices)} sample devices")
    
    print("\n✅ Sample data created successfully!")
    print("\nYou can now:")
    print("  - View devices at http://localhost:9000/devices")
    print("  - Manage device types at http://localhost:9000/admin/device-types")
    print("  - Configure credentials at http://localhost:9000/admin/credentials")
    print("  - Set up backup locations at http://localhost:9000/admin/backup-locations")

if __name__ == '__main__':
    create_sample_data()
