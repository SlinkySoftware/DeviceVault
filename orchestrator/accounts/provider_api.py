"""API for identity providers and their group mapping rules (global administrators only)."""

from django.db import transaction
from rest_framework import decorators, response, serializers, status, viewsets

from accounts.access import IsGlobalAdmin
from accounts.models import AuthProvider, GroupMappingRule, UserGroupMembership
from accounts.providers import KINDS, ProviderError
from api.serializers import secret_fields
from audit.log import record
from audit.models import AuditLog


def kind_entry(key: str) -> dict:
    kind = KINDS[key]
    return {'key': key, 'name': kind.name, 'password_login': kind.password_login, 'params_schema': kind.schema()}


class MappingRuleSerializer(serializers.ModelSerializer):
    user_group_name = serializers.CharField(source='user_group.name', read_only=True)

    class Meta:
        model = GroupMappingRule
        fields = ['external_group', 'user_group', 'user_group_name']


class AuthProviderSerializer(serializers.ModelSerializer):
    """A provider. Secret settings are write-only: left empty they keep their value; ``secrets_set`` lists them."""

    mapping_rules = MappingRuleSerializer(many=True, required=False)
    secrets_set = serializers.SerializerMethodField()
    kind_name = serializers.SerializerMethodField()
    user_count = serializers.IntegerField(source='identities.count', read_only=True)
    redirect_uri = serializers.SerializerMethodField()

    class Meta:
        model = AuthProvider
        fields = [
            'id',
            'slug',
            'name',
            'kind',
            'kind_name',
            'enabled',
            'order',
            'config',
            'secrets_set',
            'auto_create_users',
            'auto_create_groups',
            'login_group',
            'mapping_rules',
            'user_count',
            'redirect_uri',
            'created_at',
            'updated_at',
        ]

    def _secrets(self, kind: str) -> set[str]:
        return secret_fields(KINDS[kind].schema()) if kind in KINDS else set()

    def get_secrets_set(self, obj) -> list[str]:
        return sorted(name for name in self._secrets(obj.kind) if (obj.config or {}).get(name))

    def get_redirect_uri(self, obj) -> str | None:
        """Where a redirect provider (OIDC) sends users back: register it at the IdP."""
        request = self.context.get('request')
        if request is None or obj.kind not in KINDS or KINDS[obj.kind].password_login:
            return None
        return request.build_absolute_uri(f'/api/auth/oidc/{obj.slug}/callback/')

    def get_kind_name(self, obj) -> str:
        return KINDS[obj.kind].name if obj.kind in KINDS else obj.kind

    def to_representation(self, instance):
        data = super().to_representation(instance)
        secrets = self._secrets(instance.kind)
        data['config'] = {key: (None if key in secrets else value) for key, value in (instance.config or {}).items()}
        return data

    def validate_slug(self, value):
        if self.instance is not None and value != self.instance.slug:
            raise serializers.ValidationError('The slug cannot change once created.')
        if value in (UserGroupMembership.MANUAL, 'local'):
            raise serializers.ValidationError(f'"{value}" is reserved.')
        return value

    def validate_kind(self, value):
        if self.instance is not None and value != self.instance.kind:
            raise serializers.ValidationError('The kind cannot change once created.')
        if value not in KINDS:
            raise serializers.ValidationError(f'Unknown provider kind "{value}".')
        return value

    def validate(self, attrs):
        kind = attrs.get('kind', getattr(self.instance, 'kind', ''))
        if 'config' in attrs or self.instance is None:
            config = dict(attrs.get('config') or {})
            stored = self.instance.config if self.instance is not None else {}
            for name in self._secrets(kind):
                if config.get(name) in (None, '') and stored.get(name):
                    config[name] = stored[name]
            config = {name: value for name, value in config.items() if value is not None}
            errors = KINDS[kind].config_errors(config) if kind in KINDS else []
            if errors:
                raise serializers.ValidationError({'config': errors})
            attrs['config'] = config
        rules = attrs.get('mapping_rules')
        if rules is not None:
            pairs = [(rule['external_group'], rule['user_group'].pk) for rule in rules]
            if len(pairs) != len(set(pairs)):
                raise serializers.ValidationError({'mapping_rules': 'Each rule may appear once.'})
        return attrs

    @transaction.atomic
    def create(self, validated_data):
        rules = validated_data.pop('mapping_rules', [])
        provider = AuthProvider.objects.create(**validated_data)
        self._set_rules(provider, rules)
        return provider

    @transaction.atomic
    def update(self, instance, validated_data):
        rules = validated_data.pop('mapping_rules', None)
        provider = super().update(instance, validated_data)
        if rules is not None:
            self._set_rules(provider, rules)
        return provider

    def _set_rules(self, provider, rules) -> None:
        provider.mapping_rules.all().delete()
        GroupMappingRule.objects.bulk_create(GroupMappingRule(provider=provider, **rule) for rule in rules)


def provider_snapshot(provider: AuthProvider) -> dict:
    """For the audit log: settings with secrets shown only as set or not."""
    secrets = secret_fields(KINDS[provider.kind].schema()) if provider.kind in KINDS else set()
    return {
        'name': provider.name,
        'kind': provider.kind,
        'enabled': provider.enabled,
        'order': provider.order,
        'config': {key: ('(set)' if key in secrets else value) for key, value in (provider.config or {}).items()},
        'auto_create_users': provider.auto_create_users,
        'auto_create_groups': provider.auto_create_groups,
        'login_group': provider.login_group,
        'mapping_rules': sorted(
            f'{rule.external_group} -> {rule.user_group.name}'
            for rule in provider.mapping_rules.select_related('user_group')
        ),
    }


class AuthProviderViewSet(viewsets.ModelViewSet):
    """Identity providers.

    - POST {id}/test/ ``{username?}``: check the settings (and look a user up)
    - DELETE: removes the provider's identities, external groups and the memberships it added
    """

    serializer_class = AuthProviderSerializer
    permission_classes = [IsGlobalAdmin]
    queryset = AuthProvider.objects.prefetch_related('mapping_rules__user_group')

    def perform_create(self, serializer):
        provider = serializer.save()
        record(self.request, 'provider.create', resource=provider.slug, details={'after': provider_snapshot(provider)})

    def perform_update(self, serializer):
        before = provider_snapshot(serializer.instance)
        provider = serializer.save()
        record(
            self.request,
            'provider.update',
            resource=provider.slug,
            details={'before': before, 'after': provider_snapshot(provider)},
        )

    def perform_destroy(self, instance):
        before = provider_snapshot(instance)
        with transaction.atomic():
            UserGroupMembership.objects.filter(source=instance.slug).delete()
            instance.delete()
        record(self.request, 'provider.delete', resource=before['name'], details={'before': before})

    @decorators.action(detail=True, methods=['post'])
    def test(self, request, pk=None):
        provider = self.get_object()
        kind = KINDS.get(provider.kind)
        username = str(request.data.get('username') or '')[:150]
        try:
            if kind is None:
                raise ProviderError(f'unknown kind "{provider.kind}"')
            result = {'ok': True, **kind.test(kind.config(provider.config), username)}
        except ProviderError as exc:
            result = {'ok': False, 'error': str(exc)}
        record(
            request,
            'provider.test',
            resource=provider.slug,
            outcome=AuditLog.SUCCESS if result['ok'] else AuditLog.FAILURE,
            details={'username': username, **({'error': result['error']} if not result['ok'] else {})},
        )
        return response.Response(result)


class AuthProviderKindViewSet(viewsets.ViewSet):
    """The kinds of provider this orchestrator supports, with their settings schemas."""

    permission_classes = [IsGlobalAdmin]

    def list(self, request):
        return response.Response([kind_entry(key) for key in KINDS], status=status.HTTP_200_OK)
