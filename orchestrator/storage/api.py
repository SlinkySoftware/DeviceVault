"""API for storage targets and the storage drivers workers offer (global administrators only)."""

from typing import Any

from django.db import transaction
from django.db.models import Count
from rest_framework import decorators, response, serializers, status, viewsets

from accounts.access import IsGlobalAdmin, IsGlobalAdminOrReadOnly, is_global_admin
from api.serializers import driver_param_errors, secret_fields
from core import workers as registry
from core.models import Worker
from storage.models import StorageTarget
from storage.service import TargetUnavailable, check_target


class StorageTargetSerializer(serializers.ModelSerializer):
    workers = serializers.PrimaryKeyRelatedField(queryset=Worker.objects.all(), many=True, required=False)
    worker_names = serializers.SerializerMethodField()
    driver_name = serializers.SerializerMethodField()
    queue = serializers.CharField(read_only=True)
    device_count = serializers.IntegerField(read_only=True, default=0)
    job_count = serializers.IntegerField(read_only=True, default=0)
    secrets_set = serializers.SerializerMethodField()

    class Meta:
        model = StorageTarget
        fields = [
            'id',
            'name',
            'description',
            'driver',
            'driver_name',
            'config',
            'secrets_set',
            'workers',
            'worker_names',
            'queue',
            'device_count',
            'job_count',
            'created_at',
            'updated_at',
        ]

    def _catalogue(self) -> dict[str, dict[str, Any]]:
        if 'storage_drivers' not in self.context:
            self.context['storage_drivers'] = registry.storage_driver_catalogue()
        return self.context['storage_drivers']

    def _schema(self, driver_key: str) -> dict | None:
        entry = self._catalogue().get(driver_key)
        return entry['params_schema'] if entry else None

    def get_worker_names(self, obj) -> list[str]:
        return sorted(worker.name for worker in obj.workers.all())

    def get_driver_name(self, obj) -> str:
        entry = self._catalogue().get(obj.driver)
        return entry['name'] if entry else obj.driver

    def get_secrets_set(self, obj) -> list[str]:
        return sorted(name for name in secret_fields(self._schema(obj.driver)) if obj.config.get(name))

    def to_representation(self, instance):
        data = super().to_representation(instance)
        # Secrets are write-only: the form shows which are set, never their values.
        data['config'] = {
            name: (None if name in secret_fields(self._schema(instance.driver)) else value)
            for name, value in (instance.config or {}).items()
        }
        return data

    def validate_driver(self, value):
        if self.instance is not None and value == self.instance.driver:
            return value
        if value not in self._catalogue():
            raise serializers.ValidationError(f'No approved storage worker offers the "{value}" storage driver')
        return value

    def validate(self, attrs):
        driver = attrs.get('driver', getattr(self.instance, 'driver', ''))
        schema = self._schema(driver)
        new_driver = self.instance is not None and driver != self.instance.driver
        if new_driver and self.instance.jobs.exists():
            raise serializers.ValidationError({'driver': 'The driver cannot change once the target holds backups.'})
        if 'config' in attrs or new_driver or self.instance is None:
            attrs.setdefault('config', {})
            config = dict(attrs['config'] or {})
            # A secret left empty keeps its stored value (the API never returns it).
            if self.instance is not None and driver == self.instance.driver:
                for name in secret_fields(schema):
                    if config.get(name) in (None, '') and self.instance.config.get(name):
                        config[name] = self.instance.config[name]
            config = {name: value for name, value in config.items() if value is not None}
            if schema:
                errors = driver_param_errors(config, schema)
                if errors:
                    raise serializers.ValidationError({'config': errors})
            attrs['config'] = config
        workers = attrs.get('workers', list(self.instance.workers.all()) if new_driver else None)
        if workers is not None:
            problems = registry.target_worker_problems(driver, workers)
            if problems:
                raise serializers.ValidationError({'workers': problems})
        return attrs

    def create(self, validated_data):
        workers = validated_data.pop('workers', [])
        target = super().create(validated_data)
        registry.set_target_workers(target, workers)
        return target

    def update(self, instance, validated_data):
        workers = validated_data.pop('workers', None)
        with transaction.atomic():
            target = super().update(instance, validated_data)
        if workers is not None:
            registry.set_target_workers(target, workers)
        return target


class StorageTargetSummarySerializer(serializers.ModelSerializer):
    """What users other than global administrators see: enough to choose a target for a device."""

    class Meta:
        model = StorageTarget
        fields = ['id', 'name', 'description', 'driver']
        read_only_fields = fields


class StorageTargetViewSet(viewsets.ModelViewSet):
    """Storage targets, administered by global admins and readable (as a summary) by everyone.

    ``POST /api/storage-targets/{id}/check/`` asks a worker to test the settings.
    """

    permission_classes = [IsGlobalAdminOrReadOnly]

    def get_serializer_class(self):
        return StorageTargetSerializer if is_global_admin(self.request.user) else StorageTargetSummarySerializer

    def get_queryset(self):
        return StorageTarget.objects.prefetch_related('workers').annotate(
            device_count=Count('devices', distinct=True), job_count=Count('jobs', distinct=True)
        )

    def destroy(self, request, *args, **kwargs):
        target = self.get_object()
        if target.jobs.exists():
            return response.Response(
                {'error': f'"{target.name}" holds backups; move its devices elsewhere and keep it while they matter.'},
                status=status.HTTP_409_CONFLICT,
            )
        registry.release_target(target)
        target.delete()
        return response.Response(status=status.HTTP_204_NO_CONTENT)

    @decorators.action(detail=True, methods=['post'], permission_classes=[IsGlobalAdmin])
    def check(self, request, pk=None):
        try:
            return response.Response({'ok': True, **check_target(self.get_object())})
        except TargetUnavailable as exc:
            return response.Response({'ok': False, 'error': str(exc)})


class StorageDriverViewSet(viewsets.ViewSet):
    """Storage drivers offered by approved storage workers."""

    permission_classes = [IsGlobalAdmin]

    def list(self, request):
        return response.Response(list(registry.storage_driver_catalogue().values()))
