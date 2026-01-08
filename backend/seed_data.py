#!/usr/bin/env python
"""
DeviceVault Data Seeder
Creates sample data for testing and demonstration
"""
# DeviceVault - A comprehensive network device backup management application with web interface for user and admin access and backend component for automated backup collection.
# Copyright (C) 2026, Slinky Software
#
# This program is free software: you can redistribute it and/or modify
# it under the terms of the GNU General Public License as published by
# the Free Software Foundation, either version 3 of the License, or
# (at your option) any later version.
#
# This program is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
# GNU General Public License for more details.
#
# You should have received a copy of the GNU General Public License
# along with this program.  If not, see <http://www.gnu.org/licenses/>.

import os
import sys
import django

# Setup Django
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'devicevault.settings')
django.setup()

from devices.models import DeviceType, Manufacturer, Device, DeviceGroup
from credentials.models import CredentialType, Credential
from locations.models import BackupLocation
from policies.models import RetentionPolicy, BackupSchedule
from django.contrib.auth.models import User

def create_sample_data():
    print("Creating sample data...")
    
    # Device Types with appropriate network icons
    device_types_with_icons = [
        ('Router', 'router'),
        ('Switch', 'dns'),
        ('Firewall', 'security'),
        ('Access Point', 'wifi'),
        ('Load Balancer', 'cloud'),
    ]
    for name, icon in device_types_with_icons:
        DeviceType.objects.get_or_create(name=name, defaults={'icon': icon})
    print(f"✓ Created {len(device_types_with_icons)} device types with icons")
    
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
    
    # Backup Schedules
    schedules = [
        ('Daily 2 AM', 'Daily backup at 2:00 AM', 'daily', 2, 0, None, None, None, True),
        ('Weekly Friday', 'Weekly backup every Friday at 3:30 AM', 'weekly', 3, 30, '5', None, None, True),
        ('Monthly 1st', 'Monthly backup on the 1st at 4:00 AM', 'monthly', 4, 0, None, 1, None, True),
    ]
    for name, desc, schedule_type, hour, minute, day_of_week, day_of_month, cron_expr, enabled in schedules:
        BackupSchedule.objects.get_or_create(
            name=name,
            defaults={
                'description': desc,
                'schedule_type': schedule_type,
                'hour': hour,
                'minute': minute,
                'day_of_week': day_of_week or '0',
                'day_of_month': day_of_month or 1,
                'cron_expression': cron_expr or '',
                'enabled': enabled
            }
        )
    print(f"✓ Created {len(schedules)} backup schedules")
    
    # Sample Devices (only if we have required data)
    if DeviceType.objects.exists() and Manufacturer.objects.exists():
        router_type = DeviceType.objects.get(name='Router')
        switch_type = DeviceType.objects.get(name='Switch')
        firewall_type = DeviceType.objects.get(name='Firewall')
        access_point_type = DeviceType.objects.get(name='Access Point')
        
        cisco = Manufacturer.objects.get(name='Cisco')
        dell = Manufacturer.objects.get(name='Dell')
        fortigate = Manufacturer.objects.get(name='Fortigate')
        aruba = Manufacturer.objects.get(name='Aruba')
        
        default_cred = Credential.objects.first()
        default_location = BackupLocation.objects.first()
        default_policy = RetentionPolicy.objects.first()
        
        # Production devices
        production_devices = [
            ('Core-Router-01', '192.168.1.1', 'core-router-01.local', router_type, cisco, False),
            ('Core-Router-02', '192.168.1.2', 'core-router-02.local', router_type, cisco, False),
            ('Core-Switch-01', '192.168.1.10', 'core-switch-01.local', switch_type, dell, False),
            ('Core-Switch-02', '192.168.1.11', 'core-switch-02.local', switch_type, dell, False),
            ('Edge-Firewall-01', '192.168.1.254', 'firewall-01.local', firewall_type, fortigate, False),
        ]
        
        # Example/Demo devices (marked for exclusion from backups)
        example_devices = [
            ('Demo-Router-Lab', '10.0.0.1', 'demo-router.lab', router_type, cisco, True),
            ('Demo-Switch-Lab', '10.0.0.2', 'demo-switch.lab', switch_type, dell, True),
            ('Demo-AP-Lab', '10.0.0.3', 'demo-ap.lab', access_point_type, aruba, True),
        ]
        
        all_devices = production_devices + example_devices
        
        for name, ip, dns, dtype, mfg, is_example in all_devices:
            device, created = Device.objects.get_or_create(
                name=name,
                defaults={
                    'ip_address': ip,
                    'dns_name': dns,
                    'device_type': dtype,
                    'manufacturer': mfg,
                    'backup_method': 'noop',
                    'credential': default_cred,
                    'backup_location': default_location,
                    'retention_policy': default_policy,
                    'enabled': True
                }
            )
        
        print(f"✓ Created {len(production_devices)} production devices and {len(example_devices)} example devices")
    
    # Device Groups
    device_groups = [
        ('Core Network', 'Critical core network infrastructure'),
        ('Edge Network', 'Edge routers and firewalls'),
        ('Lab Equipment', 'Test and demo devices'),
        ('Access Layer', 'Access switches and wireless APs'),
    ]
    
    created_groups = {}
    for group_name, description in device_groups:
        group, _ = DeviceGroup.objects.get_or_create(
            name=group_name,
            defaults={'description': description}
        )
        created_groups[group_name] = group
    print(f"✓ Created {len(device_groups)} device groups")
    
    # Assign devices to groups
    core_routers = Device.objects.filter(name__icontains='Core-Router')
    core_switches = Device.objects.filter(name__icontains='Core-Switch')
    edge_devices = Device.objects.filter(name__icontains='Firewall')
    lab_devices = Device.objects.filter(name__icontains='Demo')
    access_devices = Device.objects.filter(name__icontains='AP')
    
    if created_groups.get('Core Network'):
        created_groups['Core Network'].device_set.set(list(core_routers) + list(core_switches))
    if created_groups.get('Edge Network'):
        created_groups['Edge Network'].device_set.set(edge_devices)
    if created_groups.get('Lab Equipment'):
        created_groups['Lab Equipment'].device_set.set(lab_devices)
    if created_groups.get('Access Layer'):
        created_groups['Access Layer'].device_set.set(access_devices)
    
    print(f"✓ Assigned devices to groups")
    
    print("\n✅ Sample data created successfully!")
    print("\nProduction devices (will be backed up):")
    print("  - 5 network devices in production environment")
    print("\nExample/Demo devices (excluded from backups):")
    print("  - 3 lab/demo devices for testing")
    print("\nYou can now:")
    print("  - View devices at http://localhost:9000/devices")
    print("  - Manage backup schedules at http://localhost:9000/vaultadmin/backup-schedules")
    print("  - Configure device types at http://localhost:9000/vaultadmin/device-types")
    print("  - Set up credentials at http://localhost:9000/vaultadmin/credentials")
    print("  - Configure backup locations at http://localhost:9000/vaultadmin/backup-locations")

if __name__ == '__main__':
    create_sample_data()
