"""
Django REST Framework Serializers
Converts database models to/from JSON for API requests and responses.
Users, groups and sign-in live in accounts.api; the audit log in audit.api.
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

from jsonschema import Draft202012Validator
from rest_framework import serializers

from accounts import access
from core.models import UserProfile, Worker
from core.workers import driver_catalogue, is_online
from credentials.models import Credential, CredentialType
from devices.models import CollectionGroup, Device, DeviceGroup, DeviceType, Manufacturer
from devicevault_protocol.push import PUSH_OFF
from devicevault_protocol.registration import ROLE_COLLECTOR, ROLE_RECEIVER, ROLE_STORAGE, ROLES, STATUS_APPROVED
from policies.models import BackupSchedule, RetentionPolicy, validate_cron
from storage.models import StorageTarget


def drivers(context: dict) -> dict:
    """Collector driver catalogue, computed once per request (the context is shared by list items)."""
    if 'drivers' not in context:
        context['drivers'] = driver_catalogue()
    return context['drivers']


# ===== Model Serializers (Standard CRUD) =====


class DeviceTypeSerializer(serializers.ModelSerializer):
    """Serializes DeviceType model for API responses"""

    class Meta:
        model = DeviceType
        fields = '__all__'


class ManufacturerSerializer(serializers.ModelSerializer):
    """Serializes Manufacturer model for API responses"""

    class Meta:
        model = Manufacturer
        fields = '__all__'


class CollectionGroupSerializer(serializers.ModelSerializer):
    """
    Serializes CollectionGroup model with device count

    Fields:
        - id: Primary key
        - name: Collection group name
        - description: Collection group description
        - rabbitmq_queue_id: RabbitMQ queue ID for task distribution
        - device_count: Read-only field showing count of devices in group
        - created_at: Timestamp when created
        - updated_at: Timestamp when last updated
    """

    device_count = serializers.SerializerMethodField()
    collector_count = serializers.SerializerMethodField()

    class Meta:
        model = CollectionGroup
        fields = [
            'id',
            'name',
            'description',
            'rabbitmq_queue_id',
            'device_count',
            'collector_count',
            'created_at',
            'updated_at',
        ]
        read_only_fields = ['created_at', 'updated_at']

    def get_collector_count(self, obj):
        """Approved collectors consuming this group's queue."""
        return obj.workers.filter(status=STATUS_APPROVED, role=ROLE_COLLECTOR).count()

    def get_device_count(self, obj):
        """Return count of devices assigned to this collection group"""
        return obj.device_count


class SummarySerializer(serializers.Serializer):
    """What users other than global administrators see of shared reference data: enough to choose it."""

    id = serializers.IntegerField(read_only=True)
    name = serializers.CharField(read_only=True)


class RetentionPolicySerializer(serializers.ModelSerializer):
    """A retention policy, with what its last retention pass found (see backups.retention)."""

    class Meta:
        model = RetentionPolicy
        fields = '__all__'
        read_only_fields = ('last_run_at', 'last_result')


class BackupScheduleSerializer(serializers.ModelSerializer):
    """A backup schedule, with when it last ran and next runs."""

    next_run = serializers.SerializerMethodField()

    class Meta:
        model = BackupSchedule
        fields = '__all__'
        read_only_fields = ('last_run_at',)

    def get_next_run(self, obj):
        return obj.next_run()

    def validate(self, attrs):
        schedule = BackupSchedule(**{**self._current(), **attrs})
        try:
            validate_cron(schedule.cron())
        except ValueError as exc:
            field = 'cron_expression' if schedule.schedule_type == 'custom_cron' else 'non_field_errors'
            raise serializers.ValidationError({field: f'Invalid schedule: {exc}'}) from exc
        return attrs

    def _current(self) -> dict:
        if self.instance is None:
            return {}
        names = ('schedule_type', 'hour', 'minute', 'day_of_week', 'day_of_month', 'cron_expression')
        return {name: getattr(self.instance, name) for name in names}


class CredentialTypeSerializer(serializers.ModelSerializer):
    """Serializes CredentialType model for API responses"""

    class Meta:
        model = CredentialType
        fields = '__all__'


class CredentialSerializer(serializers.ModelSerializer):
    """A credential. ``data`` is write-only: responses list which keys are set (``data_keys``).

    On update, a key sent as null or "" keeps its stored value, and omitting ``data`` keeps it all.
    """

    data = serializers.JSONField(write_only=True, required=False)
    data_keys = serializers.SerializerMethodField()
    device_group_name = serializers.CharField(source='device_group.name', read_only=True, default=None)

    class Meta:
        model = Credential
        fields = ['id', 'name', 'credential_type', 'device_group', 'device_group_name', 'data', 'data_keys']

    def get_data_keys(self, obj) -> list[str]:
        return sorted(key for key, value in (obj.data or {}).items() if value not in (None, ''))

    def validate_data(self, value):
        if not isinstance(value, dict):
            raise serializers.ValidationError('Credential data must be a JSON object.')
        stored = self.instance.data if self.instance is not None else {}
        merged = {key: stored.get(key) if item in (None, '') else item for key, item in value.items()}
        return {key: item for key, item in merged.items() if item is not None}


class DeviceSerializer(serializers.ModelSerializer):
    """
    Serializes Device model with nested related objects

    Nested Objects:
        - device_type (DeviceTypeSerializer): Includes icon and name
        - manufacturer (ManufacturerSerializer): Full manufacturer details (optional)
        - collection_group (CollectionGroupSerializer): Collection group assignment (optional)
        - user_permissions (SerializerMethodField): User's permissions for device's group
    """

    device_type = DeviceTypeSerializer(read_only=True)
    manufacturer = ManufacturerSerializer(read_only=True)
    collection_group = CollectionGroupSerializer(read_only=True)
    user_permissions = serializers.SerializerMethodField()
    device_group_name = serializers.CharField(source='device_group.name', read_only=True)
    backup_method_display = serializers.SerializerMethodField()

    class Meta:
        model = Device
        fields = [
            'id',
            'name',
            'ip_address',
            'dns_name',
            'device_type',
            'manufacturer',
            'backup_method',
            'driver_params',
            'backup_method_display',
            'device_group',
            'device_group_name',
            'collection_group',
            'enabled',
            'push_mode',
            'push_filename_pattern',
            'last_backup_time',
            'last_backup_status',
            'retention_policy',
            'storage_target',
            'schedule',
            'credential',
            'user_permissions',
        ]

    def get_user_permissions(self, obj):
        """The flags the requesting user holds on this device's group."""
        request = self.context.get('request')
        return access.flags_on(request.user, obj.device_group_id) if request else []

    def get_backup_method_display(self, obj):
        if not obj.backup_method:
            return 'Push only'
        driver = drivers(self.context).get(obj.backup_method)
        return driver['name'] if driver else obj.backup_method


class UserProfileSerializer(serializers.ModelSerializer):
    class Meta:
        model = UserProfile
        fields = ['theme', 'created_at', 'updated_at']


class DeviceGroupSerializer(serializers.ModelSerializer):
    """A device group, with the flags the requesting user holds on it."""

    user_permissions = serializers.SerializerMethodField()
    device_count = serializers.IntegerField(source='device_set.count', read_only=True)

    class Meta:
        model = DeviceGroup
        fields = ['id', 'name', 'description', 'device_count', 'created_at', 'updated_at', 'user_permissions']

    def get_user_permissions(self, obj):
        request = self.context.get('request')
        return access.flags_on(request.user, obj) if request else []


class DeviceDetailedSerializer(serializers.ModelSerializer):
    """
    Serializes Device model with nested related objects and RBAC info

    Nested Objects:
        - device_type (DeviceTypeSerializer): Includes icon and name
        - manufacturer (ManufacturerSerializer): Full manufacturer details
        - device_group (DeviceGroupSerializer): Device group with roles
        - collection_group (CollectionGroupSerializer): Collection group info
    """

    device_type = DeviceTypeSerializer(read_only=True)
    manufacturer = ManufacturerSerializer(read_only=True)
    device_group = DeviceGroupSerializer(read_only=True)
    collection_group = CollectionGroupSerializer(read_only=True)
    user_permissions = serializers.SerializerMethodField()
    backup_method_display = serializers.SerializerMethodField()

    class Meta:
        model = Device
        fields = [
            'id',
            'name',
            'ip_address',
            'dns_name',
            'device_type',
            'manufacturer',
            'backup_method',
            'driver_params',
            'backup_method_display',
            'device_group',
            'collection_group',
            'enabled',
            'push_mode',
            'push_filename_pattern',
            'last_backup_time',
            'last_backup_status',
            'retention_policy',
            'storage_target',
            'schedule',
            'credential',
            'user_permissions',
        ]

    def get_user_permissions(self, obj):
        """The flags the requesting user holds on this device's group."""
        request = self.context.get('request')
        return access.flags_on(request.user, obj.device_group_id) if request else []

    def get_backup_method_display(self, obj):
        if not obj.backup_method:
            return 'Push only'
        driver = drivers(self.context).get(obj.backup_method)
        return driver['name'] if driver else obj.backup_method


class DeviceWriteSerializer(serializers.ModelSerializer):
    """Accepts primary keys for related objects on create/update.

    Responses use DeviceDetailedSerializer so clients see the same shape as a retrieve.
    """

    class Meta:
        model = Device
        fields = [
            'id',
            'name',
            'ip_address',
            'dns_name',
            'device_type',
            'manufacturer',
            'backup_method',
            'driver_params',
            'device_group',
            'collection_group',
            'enabled',
            'push_mode',
            'push_filename_pattern',
            'retention_policy',
            'storage_target',
            'schedule',
            'credential',
        ]
        # Explicit, so a device never falls out of its group by omission; null (ungrouped) is for global admins.
        extra_kwargs = {'device_group': {'required': True, 'allow_null': True}}

    def validate_backup_method(self, value):
        # An unchanged method stays valid even while no collector offers it; none means push only (see validate).
        if not value or (self.instance is not None and value == self.instance.backup_method):
            return value
        if value not in drivers(self.context):
            raise serializers.ValidationError(f'No approved collector offers the backup method "{value}"')
        return value

    def validate(self, attrs):
        method = attrs.get('backup_method', getattr(self.instance, 'backup_method', None))
        params = attrs.get('driver_params', getattr(self.instance, 'driver_params', None)) or {}
        changed = 'backup_method' in attrs or 'driver_params' in attrs
        driver = drivers(self.context).get(method)
        if changed and driver and driver['params_schema']:
            errors = driver_param_errors(params, driver['params_schema'])
            if errors:
                raise serializers.ValidationError({'driver_params': errors})
        push_mode = attrs.get('push_mode', getattr(self.instance, 'push_mode', PUSH_OFF))
        if not method and push_mode == PUSH_OFF:
            raise serializers.ValidationError({'backup_method': 'Choose a backup method, or let the device push.'})
        storage_target = attrs.get('storage_target', getattr(self.instance, 'storage_target', None))
        if push_mode != PUSH_OFF and storage_target is None:
            raise serializers.ValidationError({'storage_target': 'A device that pushes needs a storage target.'})
        # A device uses a global credential, or one owned by its own group.
        credential = attrs.get('credential', getattr(self.instance, 'credential', None))
        group = attrs.get('device_group', getattr(self.instance, 'device_group', None))
        if credential is not None and credential.device_group_id not in (None, getattr(group, 'pk', None)):
            raise serializers.ValidationError(
                {'credential': "Use a global credential or one owned by the device's group."}
            )
        return attrs

    def to_representation(self, instance):
        return DeviceDetailedSerializer(instance, context=self.context).data


class WorkerSerializer(serializers.ModelSerializer):
    """A registered worker, with its assignment and liveness."""

    storage_targets = serializers.PrimaryKeyRelatedField(
        queryset=StorageTarget.objects.all(), many=True, required=False
    )
    is_online = serializers.SerializerMethodField()
    in_sync = serializers.SerializerMethodField()
    assigned_queues = serializers.SerializerMethodField()
    pinned_orchestrator_matches = serializers.SerializerMethodField()
    approved_by_username = serializers.CharField(source='approved_by.username', read_only=True, default=None)

    class Meta:
        model = Worker
        fields = [
            'id',
            'name',
            'celery_hostname',
            'hostname',
            'pid',
            'version',
            'status',
            'role',
            'collection_groups',
            'storage_targets',
            'fingerprint',
            'capabilities',
            'desired_version',
            'applied_version',
            'applied_queues',
            'assigned_queues',
            'runtime',
            'in_sync',
            'pinned_orchestrator_matches',
            'registered_at',
            'approved_at',
            'approved_by_username',
            'last_seen_at',
            'is_online',
        ]
        read_only_fields = [f for f in fields if f not in ('name', 'role', 'collection_groups', 'storage_targets')]

    def get_is_online(self, obj):
        return is_online(obj)

    def get_in_sync(self, obj):
        return obj.applied_version == obj.desired_version

    def get_assigned_queues(self, obj):
        return obj.assigned_queues()

    def get_pinned_orchestrator_matches(self, obj):
        from core.signing import public_key

        return obj.pinned_orchestrator_key == public_key() if obj.pinned_orchestrator_key else None

    def validate(self, attrs):
        role = attrs.get('role', getattr(self.instance, 'role', ''))
        capabilities = getattr(self.instance, 'capabilities', {}) or {}
        if role == ROLE_COLLECTOR and not capabilities.get('collector_drivers'):
            raise serializers.ValidationError({'role': 'This worker offers no collector drivers.'})
        if role == ROLE_STORAGE and not capabilities.get('storage_drivers'):
            raise serializers.ValidationError({'role': 'This worker offers no storage drivers.'})
        if role == ROLE_RECEIVER and not capabilities.get('receiver'):
            raise serializers.ValidationError({'role': 'This worker is not a push receiver.'})
        if role != ROLE_RECEIVER and capabilities.get('receiver'):
            raise serializers.ValidationError({'role': 'A push receiver can only be approved as a receiver.'})
        if self.instance is not None and attrs.get('storage_targets'):
            from core.workers import approval_target_problems

            problems = approval_target_problems(self.instance, attrs['storage_targets'])
            if problems:
                raise serializers.ValidationError({'storage_targets': problems})
        return attrs


class WorkerApprovalSerializer(serializers.Serializer):
    role = serializers.ChoiceField(choices=ROLES)
    collection_groups = serializers.PrimaryKeyRelatedField(
        queryset=CollectionGroup.objects.all(), many=True, required=False
    )
    storage_targets = serializers.PrimaryKeyRelatedField(
        queryset=StorageTarget.objects.all(), many=True, required=False
    )


def driver_param_errors(params: dict, schema: dict) -> list[str]:
    """Problems with a device's driver parameters, checked against the driver's JSON schema."""
    validator = Draft202012Validator(schema)
    return [
        f'{".".join(str(part) for part in error.absolute_path) or "parameters"}: {error.message}'
        for error in sorted(validator.iter_errors(params), key=lambda error: list(error.absolute_path))
    ]


def secret_fields(schema: dict | None) -> set[str]:
    """Settings a schema marks secret (``writeOnly``, e.g. pydantic ``SecretStr``)."""

    def secret(prop: dict) -> bool:
        return bool(prop.get('writeOnly')) or any(secret(option) for option in prop.get('anyOf', []))

    return {name for name, prop in ((schema or {}).get('properties') or {}).items() if secret(prop)}
