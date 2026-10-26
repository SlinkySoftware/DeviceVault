"""API for API tokens (a user's own, and every token for global administrators) and service accounts.

Tokens are managed from a signed-in session only: a token can never mint or
revoke tokens. Service accounts are users that cannot sign in and exist to own
tokens; only global administrators manage them, and they never belong to a
global-administrator group.
"""

import ipaddress
from datetime import timedelta

from django.conf import settings
from django.contrib.auth.models import User
from django.db import transaction
from django.utils import timezone
from rest_framework import decorators, mixins, response, serializers, status, viewsets
from rest_framework.permissions import IsAuthenticated

from accounts import access, tokens
from accounts.access import IsGlobalAdmin
from accounts.authentication import SessionAuthentication
from accounts.login import is_service_account
from accounts.models import ApiToken, UserGroup, UserGroupMembership
from audit.log import record
from core.models import UserProfile

SERVICE_ACCOUNT_ADMIN = 'Service accounts cannot be members of a global-administrator group.'


def service_accounts():
    return User.objects.filter(profile__is_service_account=True)


class TokenSerializer(serializers.ModelSerializer):
    """A token as listed: never its secret. ``expires_in_days`` sets the expiry on creation."""

    username = serializers.CharField(source='user.username', read_only=True)
    created_by_username = serializers.CharField(source='created_by.username', read_only=True, default=None)
    expires_in_days = serializers.IntegerField(write_only=True, required=False, min_value=1)
    scopes = serializers.ListField(child=serializers.ChoiceField(choices=ApiToken.SCOPES), allow_empty=False)
    allowed_networks = serializers.ListField(
        child=serializers.CharField(max_length=64), required=False, max_length=tokens.MAX_NETWORKS
    )
    state = serializers.SerializerMethodField()

    class Meta:
        model = ApiToken
        fields = [
            'id',
            'name',
            'prefix',
            'username',
            'scopes',
            'allowed_networks',
            'expires_in_days',
            'expires_at',
            'created_at',
            'created_by_username',
            'last_used_at',
            'last_used_address',
            'revoked_at',
            'state',
        ]
        read_only_fields = ['prefix', 'expires_at', 'created_at', 'last_used_at', 'last_used_address', 'revoked_at']

    def get_state(self, obj) -> str:
        if obj.revoked_at is not None:
            return 'revoked'
        return 'live' if obj.expires_at > timezone.now() else 'expired'

    def validate_expires_in_days(self, value):
        limit = settings.DEVICEVAULT_API_TOKEN_MAX_DAYS
        if value > limit:
            raise serializers.ValidationError(f'Tokens expire within {limit} days at most.')
        return value

    def validate_allowed_networks(self, value):
        networks = []
        for entry in value:
            try:
                networks.append(str(ipaddress.ip_network(entry.strip(), strict=False)))
            except ValueError:
                raise serializers.ValidationError(f'{entry!r} is not an address or network.') from None
        return list(dict.fromkeys(networks))

    def validate_scopes(self, value):
        owner = self.context['owner']
        scopes = tokens.normalise_scopes(value)
        if ApiToken.MONITORING_PLATFORM in scopes:
            if not is_service_account(owner):
                raise serializers.ValidationError('Platform metrics are for service accounts only.')
            if not access.is_global_admin(self.context['request'].user):
                raise serializers.ValidationError('Only global administrators grant platform metrics.')
        return scopes

    def validate_name(self, value):
        if tokens.live_tokens(self.context['owner']).filter(name=value).exists():
            raise serializers.ValidationError('A live token already has this name.')
        return value

    def validate(self, attrs):
        if tokens.live_tokens(self.context['owner']).count() >= tokens.MAX_LIVE_PER_USER:
            raise serializers.ValidationError(f'At most {tokens.MAX_LIVE_PER_USER} live tokens per user.')
        return attrs

    def create(self, validated_data):
        days = validated_data.pop('expires_in_days', None) or min(
            tokens.DEFAULT_DAYS, settings.DEVICEVAULT_API_TOKEN_MAX_DAYS
        )
        token, raw = tokens.issue(
            self.context['owner'],
            name=validated_data['name'],
            scopes=validated_data['scopes'],
            allowed_networks=validated_data.get('allowed_networks', []),
            expires_at=timezone.now() + timedelta(days=days),
            created_by=self.context['request'].user,
        )
        token.raw = raw
        return token


def _create_token(request, owner) -> response.Response:
    form = TokenSerializer(data=request.data, context={'request': request, 'owner': owner})
    form.is_valid(raise_exception=True)
    with transaction.atomic():
        token = form.save()
        record(request, 'token.create', resource=token.prefix, details=tokens.snapshot(token))
        if tokens.is_relay_token(token):
            tokens.relays_changed()
    return response.Response({**TokenSerializer(token).data, 'token': token.raw}, status=status.HTTP_201_CREATED)


class SessionOnly:
    """Token management needs a signed-in session: tokens never mint or revoke tokens."""

    authentication_classes = [SessionAuthentication]
    token_scopes = ()


class TokenViewSet(SessionOnly, mixins.ListModelMixin, viewsets.GenericViewSet):
    """The signed-in user's own tokens.

    - POST: create one; the response holds the token, shown this once
    - POST {id}/revoke/: revoke it
    """

    serializer_class = TokenSerializer
    permission_classes = [IsAuthenticated]

    def get_queryset(self):
        return ApiToken.objects.filter(user=self.request.user, revoked_at__isnull=True).select_related(
            'user', 'created_by'
        )

    def create(self, request):
        return _create_token(request, request.user)

    @decorators.action(detail=True, methods=['post'])
    def revoke(self, request, pk=None):
        tokens.revoke(request, self.get_object())
        return response.Response(status=status.HTTP_204_NO_CONTENT)


class AdminTokenViewSet(SessionOnly, mixins.ListModelMixin, viewsets.GenericViewSet):
    """Every token that has not been revoked, of every user (global administrators only).

    - POST {id}/revoke/: revoke it
    """

    serializer_class = TokenSerializer
    permission_classes = [IsGlobalAdmin]
    queryset = ApiToken.objects.filter(revoked_at__isnull=True).select_related('user', 'created_by')

    @decorators.action(detail=True, methods=['post'])
    def revoke(self, request, pk=None):
        tokens.revoke(request, self.get_object())
        return response.Response(status=status.HTTP_204_NO_CONTENT)


class ServiceAccountSerializer(serializers.ModelSerializer):
    groups = serializers.PrimaryKeyRelatedField(
        source='user_groups', queryset=UserGroup.objects.filter(source=UserGroup.INTERNAL), many=True, required=False
    )
    group_names = serializers.SerializerMethodField()
    description = serializers.CharField(max_length=200, required=False, allow_blank=True)
    live_tokens = serializers.SerializerMethodField()

    class Meta:
        model = User
        fields = ['id', 'username', 'description', 'is_active', 'groups', 'group_names', 'live_tokens', 'date_joined']
        read_only_fields = ['date_joined']

    def get_group_names(self, obj) -> list[str]:
        return sorted(group.name for group in obj.user_groups.all())

    def get_live_tokens(self, obj) -> int:
        now = timezone.now()
        return sum(1 for token in obj.api_tokens.all() if tokens.is_live(token, now))

    def to_representation(self, instance):
        data = super().to_representation(instance)
        data['description'] = getattr(getattr(instance, 'profile', None), 'description', '')
        return data

    def validate_username(self, value):
        if self.instance is not None and value != self.instance.username:
            raise serializers.ValidationError('Usernames cannot be changed.')
        return value

    def validate_groups(self, value):
        if any(group.is_global_admin for group in value):
            raise serializers.ValidationError(SERVICE_ACCOUNT_ADMIN)
        return value

    def create(self, validated_data):
        groups = validated_data.pop('user_groups', [])
        description = validated_data.pop('description', '')
        user = User(**validated_data)
        user.set_unusable_password()
        user.save()
        UserProfile.objects.update_or_create(
            user=user, defaults={'is_service_account': True, 'description': description}
        )
        self._set_groups(user, groups)
        return user

    def update(self, instance, validated_data):
        groups = validated_data.pop('user_groups', None)
        description = validated_data.pop('description', None)
        user = super().update(instance, validated_data)
        if description is not None:
            UserProfile.objects.filter(user=user).update(description=description)
        if groups is not None:
            self._set_groups(user, groups)
        return user

    def _set_groups(self, user, groups) -> None:
        wanted = {group.pk for group in groups}
        UserGroupMembership.objects.filter(user=user).exclude(group_id__in=wanted).delete()
        have = set(UserGroupMembership.objects.filter(user=user).values_list('group_id', flat=True))
        UserGroupMembership.objects.bulk_create(
            UserGroupMembership(user=user, group_id=group_id) for group_id in wanted - have
        )
        access.forget(user)


def account_snapshot(user) -> dict:
    return {
        'username': user.username,
        'description': getattr(getattr(user, 'profile', None), 'description', ''),
        'is_active': user.is_active,
        'groups': sorted(user.user_groups.values_list('name', flat=True)),
    }


class ServiceAccountViewSet(SessionOnly, viewsets.ModelViewSet):
    """Service accounts (global administrators only).

    - GET/POST {id}/tokens/: the account's tokens; POST creates one, shown once
    """

    serializer_class = ServiceAccountSerializer
    permission_classes = [IsGlobalAdmin]

    def get_queryset(self):
        return (
            service_accounts()
            .select_related('profile')
            .prefetch_related('user_groups', 'api_tokens')
            .order_by('username')
        )

    def perform_create(self, serializer):
        user = serializer.save()
        record(self.request, 'service_account.create', resource=user.username, details=account_snapshot(user))

    def perform_update(self, serializer):
        before = account_snapshot(serializer.instance)
        user = serializer.save()
        record(
            self.request,
            'service_account.update',
            resource=user.username,
            details={'before': before, 'after': account_snapshot(user)},
        )
        # Its active flag decides whether relays accept its tokens, its groups what its snapshot holds.
        tokens.relays_changed()

    def perform_destroy(self, instance):
        before = account_snapshot(instance)
        instance.delete()
        record(self.request, 'service_account.delete', resource=before['username'], details=before)
        tokens.relays_changed()

    @decorators.action(detail=True, methods=['get', 'post'])
    def tokens(self, request, pk=None):
        account = self.get_object()
        if request.method == 'POST':
            return _create_token(request, account)
        rows = account.api_tokens.filter(revoked_at__isnull=True).select_related('user', 'created_by')
        return response.Response(TokenSerializer(rows, many=True).data)
