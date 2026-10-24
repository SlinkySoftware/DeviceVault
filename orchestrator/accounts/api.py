"""API for signing in and out, the current user, and (global administrators) users and user groups."""

from contextlib import contextmanager

from django.conf import settings
from django.contrib.auth import authenticate, login, logout, update_session_auth_hash
from django.contrib.auth.models import User
from django.contrib.auth.password_validation import validate_password
from django.core.exceptions import ValidationError as DjangoValidationError
from django.db import transaction
from django.utils.decorators import method_decorator
from django.views.decorators.csrf import csrf_protect, ensure_csrf_cookie
from rest_framework import decorators, response, serializers, status, viewsets
from rest_framework.permissions import AllowAny, IsAuthenticated
from rest_framework.views import APIView

from accounts import access, sessions
from accounts.access import IsGlobalAdmin
from accounts.models import FLAGS, REQUIRES, DeviceGroupGrant, UserGroup, UserGroupMembership
from accounts.throttle import LOGIN, locked_out
from audit.log import client_ip, record
from audit.models import AuditLog
from devices.models import DeviceGroup

INVALID_LOGIN = 'Invalid username or password.'
LOCKED_OUT = 'Too many failed sign-in attempts. Try again later.'
LAST_ADMIN = 'This would leave no active global administrator.'


def user_source(user) -> str:
    """``local`` for password accounts; ``external`` for accounts an identity provider manages."""
    return 'local' if user.has_usable_password() else 'external'


def current_user(user) -> dict:
    """The signed-in user as the UI needs it: identity plus effective permissions."""
    return {
        'id': user.pk,
        'username': user.username,
        'email': user.email,
        'first_name': user.first_name,
        'last_name': user.last_name,
        'source': user_source(user),
        'editable': user_source(user) == 'local',
        'is_global_admin': access.is_global_admin(user),
        'grants': {
            str(group_id): [f for f in FLAGS if f in flags] for group_id, flags in access.grants_for(user).items()
        },
    }


@contextmanager
def keeping_an_admin():
    """Apply a change atomically, refusing it if it removes the last active global administrator."""
    with transaction.atomic():
        had_admin = access.active_global_admins().exists()
        yield
        if had_admin and not access.active_global_admins().exists():
            raise serializers.ValidationError({'detail': LAST_ADMIN})


def password_errors(password: str, user=None) -> list[str]:
    try:
        validate_password(password, user)
    except DjangoValidationError as exc:
        return list(exc.messages)
    return []


# ===== Signing in =====


class LoginSerializer(serializers.Serializer):
    username = serializers.CharField(max_length=150)
    password = serializers.CharField(style={'input_type': 'password'}, trim_whitespace=False)


class CsrfView(APIView):
    """Sets the CSRF cookie the UI echoes in ``X-CSRFToken``."""

    authentication_classes = []
    permission_classes = [AllowAny]

    @method_decorator(ensure_csrf_cookie)
    def get(self, request):
        return response.Response(status=status.HTTP_204_NO_CONTENT)


@method_decorator(csrf_protect, name='dispatch')
class LoginView(APIView):
    """Local sign-in. Unknown users and wrong passwords get the same answer; repeated failures lock out."""

    authentication_classes = []
    permission_classes = [AllowAny]

    def post(self, request):
        form = LoginSerializer(data=request.data)
        form.is_valid(raise_exception=True)
        username, password = form.validated_data['username'], form.validated_data['password']

        if locked_out(username, client_ip(request)):
            record(request, LOGIN, outcome=AuditLog.FAILURE, actor_name=username, details={'reason': 'locked_out'})
            return response.Response({'detail': LOCKED_OUT}, status=status.HTTP_429_TOO_MANY_REQUESTS)
        user = authenticate(request._request, username=username, password=password)
        if user is None:
            record(request, LOGIN, outcome=AuditLog.FAILURE, actor_name=username, details={'reason': 'bad_credentials'})
            return response.Response({'detail': INVALID_LOGIN}, status=status.HTTP_400_BAD_REQUEST)

        login(request._request, user)
        sessions.start(request._request)
        record(request, LOGIN, actor=user, details={'provider': 'local'})
        return response.Response({'user': current_user(user)})


class LogoutView(APIView):
    permission_classes = [IsAuthenticated]

    def post(self, request):
        record(request, 'auth.logout')
        logout(request._request)
        return response.Response(status=status.HTTP_204_NO_CONTENT)


class AuthConfigView(APIView):
    """What the login page offers."""

    authentication_classes = []
    permission_classes = [AllowAny]

    def get(self, request):
        local_enabled = settings.DEVICEVAULT_LOCAL_AUTH_ENABLED
        return response.Response({'providers': ['Local'], 'local_enabled': local_enabled})


# ===== The current user =====


class ProfileSerializer(serializers.ModelSerializer):
    class Meta:
        model = User
        fields = ['email', 'first_name', 'last_name']


class CurrentUserView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request):
        return response.Response(current_user(request.user))

    def patch(self, request):
        if user_source(request.user) != 'local':
            return response.Response(
                {'detail': 'Your profile is managed by your identity provider.'}, status=status.HTTP_403_FORBIDDEN
            )
        form = ProfileSerializer(request.user, data=request.data, partial=True)
        form.is_valid(raise_exception=True)
        form.save()
        return response.Response(current_user(request.user))


class ChangePasswordSerializer(serializers.Serializer):
    current_password = serializers.CharField(trim_whitespace=False)
    new_password = serializers.CharField(trim_whitespace=False)

    def validate(self, data):
        user = self.context['request'].user
        if user_source(user) != 'local':
            raise serializers.ValidationError('Your password is managed by your identity provider.')
        if not user.check_password(data['current_password']):
            raise serializers.ValidationError({'current_password': 'Current password is incorrect.'})
        errors = password_errors(data['new_password'], user)
        if errors:
            raise serializers.ValidationError({'new_password': errors})
        return data


class ChangePasswordView(APIView):
    permission_classes = [IsAuthenticated]

    def post(self, request):
        form = ChangePasswordSerializer(data=request.data, context={'request': request})
        form.is_valid(raise_exception=True)
        request.user.set_password(form.validated_data['new_password'])
        request.user.save()
        # Changing the password ends the user's other sessions, but keeps this one.
        update_session_auth_hash(request._request, request.user)
        record(request, 'user.password_change', resource=request.user.username)
        return response.Response(status=status.HTTP_204_NO_CONTENT)


# ===== Users =====


def user_snapshot(user) -> dict:
    return {
        'username': user.username,
        'email': user.email,
        'first_name': user.first_name,
        'last_name': user.last_name,
        'is_active': user.is_active,
        'groups': sorted(user.user_groups.values_list('name', flat=True)),
    }


def set_manual_memberships(user, groups) -> None:
    """Make ``groups`` the user's manual memberships, leaving provider-sourced ones alone."""
    wanted = {group.pk for group in groups}
    manual = UserGroupMembership.objects.filter(user=user, source=UserGroupMembership.MANUAL)
    manual.exclude(group_id__in=wanted).delete()
    have = set(UserGroupMembership.objects.filter(user=user).values_list('group_id', flat=True))
    UserGroupMembership.objects.bulk_create(
        UserGroupMembership(user=user, group_id=group_id) for group_id in wanted - have
    )
    access.forget(user)


class UserSerializer(serializers.ModelSerializer):
    # Manual memberships of internal groups; provider-sourced memberships are kept as they are.
    groups = serializers.PrimaryKeyRelatedField(
        source='user_groups', queryset=UserGroup.objects.filter(source=UserGroup.INTERNAL), many=True, required=False
    )
    group_names = serializers.SerializerMethodField()
    source = serializers.SerializerMethodField()
    is_global_admin = serializers.SerializerMethodField()
    password = serializers.CharField(write_only=True, required=False, trim_whitespace=False)

    class Meta:
        model = User
        fields = [
            'id',
            'username',
            'email',
            'first_name',
            'last_name',
            'is_active',
            'source',
            'groups',
            'group_names',
            'is_global_admin',
            'last_login',
            'date_joined',
            'password',
        ]
        read_only_fields = ['last_login', 'date_joined']

    def get_group_names(self, obj) -> list[str]:
        return sorted(group.name for group in obj.user_groups.all())

    def get_source(self, obj) -> str:
        return user_source(obj)

    def get_is_global_admin(self, obj) -> bool:
        return obj.is_active and any(group.is_global_admin for group in obj.user_groups.all())

    def validate_username(self, value):
        if self.instance is not None and value != self.instance.username:
            raise serializers.ValidationError('Usernames cannot be changed.')
        return value

    def validate(self, attrs):
        if self.instance is None:
            if not settings.DEVICEVAULT_LOCAL_AUTH_ENABLED:
                raise serializers.ValidationError('Local accounts cannot be created while local sign-in is disabled.')
            if not attrs.get('password'):
                raise serializers.ValidationError({'password': 'A password is required.'})
        elif 'password' in attrs:
            raise serializers.ValidationError({'password': 'Use the set_password action.'})
        if 'password' in attrs:
            candidate = User(username=attrs.get('username', ''), email=attrs.get('email', ''))
            errors = password_errors(attrs['password'], candidate)
            if errors:
                raise serializers.ValidationError({'password': errors})
        return attrs

    def create(self, validated_data):
        groups = validated_data.pop('user_groups', [])
        password = validated_data.pop('password')
        user = User(**validated_data)
        user.set_password(password)
        user.save()
        set_manual_memberships(user, groups)
        return user

    def update(self, instance, validated_data):
        groups = validated_data.pop('user_groups', None)
        user = super().update(instance, validated_data)
        if groups is not None:
            set_manual_memberships(user, groups)
        return user


class SetPasswordSerializer(serializers.Serializer):
    password = serializers.CharField(trim_whitespace=False)


class UserViewSet(viewsets.ModelViewSet):
    """User accounts (global administrators only).

    - POST {id}/set_password/: set a local user's password (ends their sessions)
    """

    serializer_class = UserSerializer
    permission_classes = [IsGlobalAdmin]
    queryset = User.objects.prefetch_related('user_groups').order_by('username')

    def perform_create(self, serializer):
        user = serializer.save()
        record(self.request, 'user.create', resource=user.username, details={'after': user_snapshot(user)})

    def perform_update(self, serializer):
        user = serializer.instance
        if user == self.request.user and serializer.validated_data.get('is_active') is False:
            raise serializers.ValidationError({'is_active': 'You cannot disable your own account.'})
        before = user_snapshot(user)
        with keeping_an_admin():
            user = serializer.save()
        record(
            self.request,
            'user.update',
            resource=user.username,
            details={'before': before, 'after': user_snapshot(user)},
        )

    def perform_destroy(self, instance):
        if instance == self.request.user:
            raise serializers.ValidationError({'detail': 'You cannot delete your own account.'})
        before = user_snapshot(instance)
        with keeping_an_admin():
            instance.delete()
        record(self.request, 'user.delete', resource=before['username'], details={'before': before})

    @decorators.action(detail=True, methods=['post'])
    def set_password(self, request, pk=None):
        user = self.get_object()
        if user_source(user) != 'local':
            return response.Response(
                {'detail': "This user's password is managed by an identity provider."},
                status=status.HTTP_400_BAD_REQUEST,
            )
        form = SetPasswordSerializer(data=request.data)
        form.is_valid(raise_exception=True)
        errors = password_errors(form.validated_data['password'], user)
        if errors:
            return response.Response({'password': errors}, status=status.HTTP_400_BAD_REQUEST)
        user.set_password(form.validated_data['password'])
        user.save()
        if user == request.user:
            update_session_auth_hash(request._request, user)
        record(request, 'user.set_password', resource=user.username)
        return response.Response(status=status.HTTP_204_NO_CONTENT)


# ===== User groups and their grants =====


class GrantSerializer(serializers.Serializer):
    """One device group's permissions within a user group. ``admin`` implies every other flag."""

    device_group = serializers.PrimaryKeyRelatedField(queryset=DeviceGroup.objects.all())
    device_group_name = serializers.CharField(source='device_group.name', read_only=True)
    view = serializers.BooleanField(default=True)
    backup_now = serializers.BooleanField(default=False)
    view_contents = serializers.BooleanField(default=False)
    download = serializers.BooleanField(default=False)
    admin = serializers.BooleanField(default=False)

    def validate(self, attrs):
        # Defaults are not applied within a partial update of the user group.
        for flag in FLAGS:
            attrs.setdefault(flag, flag == 'view')
        if attrs['admin']:
            attrs.update(dict.fromkeys(FLAGS, True))
        if not attrs['view']:
            raise serializers.ValidationError('Every grant includes view; remove the device group to revoke access.')
        for flag in FLAGS:
            missing = [needed for needed in REQUIRES[flag] if attrs[flag] and not attrs[needed]]
            if missing:
                raise serializers.ValidationError(f'{flag} needs {", ".join(missing)}.')
        return attrs


def group_snapshot(group) -> dict:
    return {
        'name': group.name,
        'is_global_admin': group.is_global_admin,
        'members': sorted(group.members.values_list('username', flat=True)),
        'grants': {grant.device_group.name: grant.flags() for grant in group.grants.select_related('device_group')},
    }


class UserGroupSerializer(serializers.ModelSerializer):
    members = serializers.PrimaryKeyRelatedField(queryset=User.objects.all(), many=True, required=False)
    member_names = serializers.SerializerMethodField()
    grants = GrantSerializer(many=True, required=False)

    class Meta:
        model = UserGroup
        fields = [
            'id',
            'name',
            'description',
            'is_global_admin',
            'is_builtin',
            'source',
            'members',
            'member_names',
            'grants',
            'created_at',
            'updated_at',
        ]
        read_only_fields = ['is_builtin', 'source', 'created_at', 'updated_at']

    def get_member_names(self, obj) -> list[str]:
        return sorted(user.username for user in obj.members.all())

    def validate_grants(self, value):
        groups = [row['device_group'].pk for row in value]
        if len(groups) != len(set(groups)):
            raise serializers.ValidationError('Each device group may appear once.')
        return value

    def validate(self, attrs):
        group = self.instance
        if group is not None and group.is_builtin and attrs.get('is_global_admin') is False:
            raise serializers.ValidationError({'is_global_admin': 'The Administrators group is always global.'})
        if group is not None and group.source == UserGroup.EXTERNAL and 'members' in attrs:
            raise serializers.ValidationError({'members': 'External groups are filled by their identity provider.'})
        return attrs

    def create(self, validated_data):
        members = validated_data.pop('members', [])
        grants = validated_data.pop('grants', [])
        group = UserGroup.objects.create(**validated_data)
        self._set_members(group, members)
        self._set_grants(group, grants)
        return group

    def update(self, instance, validated_data):
        members = validated_data.pop('members', None)
        grants = validated_data.pop('grants', None)
        group = super().update(instance, validated_data)
        if members is not None:
            self._set_members(group, members)
        if grants is not None:
            self._set_grants(group, grants)
        return group

    def _set_members(self, group, users) -> None:
        wanted = {user.pk for user in users}
        group.memberships.filter(source=UserGroupMembership.MANUAL).exclude(user_id__in=wanted).delete()
        have = set(group.memberships.values_list('user_id', flat=True))
        UserGroupMembership.objects.bulk_create(
            UserGroupMembership(user_id=user_id, group=group) for user_id in wanted - have
        )

    def _set_grants(self, group, rows) -> None:
        group.grants.all().delete()
        DeviceGroupGrant.objects.bulk_create(DeviceGroupGrant(user_group=group, **row) for row in rows)


class UserGroupViewSet(viewsets.ModelViewSet):
    """User groups with their members and device-group grants (global administrators only)."""

    serializer_class = UserGroupSerializer
    permission_classes = [IsGlobalAdmin]
    queryset = UserGroup.objects.prefetch_related('members', 'grants__device_group')

    def perform_create(self, serializer):
        group = serializer.save()
        record(self.request, 'user_group.create', resource=group.name, details={'after': group_snapshot(group)})

    def perform_update(self, serializer):
        before = group_snapshot(serializer.instance)
        with keeping_an_admin():
            group = serializer.save()
        record(
            self.request,
            'user_group.update',
            resource=group.name,
            details={'before': before, 'after': group_snapshot(group)},
        )

    def perform_destroy(self, instance):
        if instance.is_builtin:
            raise serializers.ValidationError({'detail': 'The Administrators group cannot be deleted.'})
        before = group_snapshot(instance)
        with keeping_an_admin():
            instance.delete()
        record(self.request, 'user_group.delete', resource=before['name'], details={'before': before})
