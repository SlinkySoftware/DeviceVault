
from rest_framework import serializers
from devices.models import DeviceType, Manufacturer, Device
from backups.models import Backup
from policies.models import RetentionPolicy
from locations.models import BackupLocation
from credentials.models import Credential, CredentialType
from core.models import Label
from rbac.models import Role, Permission
from audit.models import AuditLog
from django.contrib.auth.models import User
class DeviceTypeSerializer(serializers.ModelSerializer):
    class Meta: model = DeviceType; fields='__all__'
class ManufacturerSerializer(serializers.ModelSerializer):
    class Meta: model = Manufacturer; fields='__all__'
class LabelSerializer(serializers.ModelSerializer):
    class Meta: model = Label; fields='__all__'
class RetentionPolicySerializer(serializers.ModelSerializer):
    class Meta: model = RetentionPolicy; fields='__all__'
class BackupLocationSerializer(serializers.ModelSerializer):
    class Meta: model = BackupLocation; fields='__all__'
class CredentialTypeSerializer(serializers.ModelSerializer):
    class Meta: model = CredentialType; fields='__all__'
class CredentialSerializer(serializers.ModelSerializer):
    class Meta: model = Credential; fields='__all__'
class DeviceSerializer(serializers.ModelSerializer):
    class Meta: model = Device; fields='__all__'
class BackupSerializer(serializers.ModelSerializer):
    class Meta: model = Backup; fields='__all__'
class PermissionSerializer(serializers.ModelSerializer):
    class Meta: model = Permission; fields='__all__'
class RoleSerializer(serializers.ModelSerializer):
    class Meta: model = Role; fields='__all__'
class UserSerializer(serializers.ModelSerializer):
    class Meta: model = User; fields=['id','username','email','first_name','last_name']
class AuditLogSerializer(serializers.ModelSerializer):
    actor_name = serializers.CharField(source='actor.username', read_only=True)
    class Meta: model = AuditLog; fields='__all__'
