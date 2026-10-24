"""API serializers for receivers: their settings and the pushes they refused (global administrators only).

The endpoints are actions on the worker viewset (``api.views.WorkerViewSet``):
``workers/{id}/receiver/`` and ``workers/{id}/rejections/``.
"""

import base64
import binascii

from rest_framework import serializers

from push.models import PushRejection, ReceiverSettings

# Public key types devices are likely to use (OpenSSH authorized_keys names).
KEY_TYPES = {
    'ssh-ed25519',
    'ssh-rsa',
    'ecdsa-sha2-nistp256',
    'ecdsa-sha2-nistp384',
    'ecdsa-sha2-nistp521',
    'sk-ssh-ed25519@openssh.com',
    'sk-ecdsa-sha2-nistp256@openssh.com',
}


def authorized_key_errors(text: str) -> list[str]:
    """Lines of an authorized_keys text that are not ``<type> <base64 key> [comment]``.

    Options before the key type (``from=...``) are not supported: the receiver
    checks the source address itself.
    """
    errors = []
    for number, line in enumerate(text.splitlines(), start=1):
        line = line.strip()
        if not line or line.startswith('#'):
            continue
        parts = line.split()
        if len(parts) < 2 or parts[0] not in KEY_TYPES:
            errors.append(f'line {number}: expected "<key type> <key> [comment]" with a supported key type')
            continue
        try:
            blob = base64.b64decode(parts[1], validate=True)
        except binascii.Error, ValueError:
            errors.append(f'line {number}: the key is not valid base64')
            continue
        # The key blob starts with its own type name, length-prefixed.
        if blob[4 : 4 + int.from_bytes(blob[:4], 'big')].decode('ascii', 'replace') != parts[0]:
            errors.append(f'line {number}: the key does not match its type {parts[0]}')
    return errors


class ReceiverSettingsSerializer(serializers.ModelSerializer):
    """Settings of one receiver. The password is write-only: omit it to keep it, send "" to remove it."""

    ssh_password = serializers.CharField(
        write_only=True, required=False, allow_blank=True, trim_whitespace=False, max_length=256
    )
    ssh_password_set = serializers.SerializerMethodField()

    class Meta:
        model = ReceiverSettings
        fields = [
            'bind_address',
            'max_file_size',
            'ssh_enabled',
            'ssh_port',
            'ssh_username',
            'ssh_password',
            'ssh_password_set',
            'ssh_authorized_keys',
            'updated_at',
        ]
        read_only_fields = ['updated_at']

    def get_ssh_password_set(self, obj) -> bool:
        return bool(obj.ssh_password)

    def validate_ssh_authorized_keys(self, value):
        errors = authorized_key_errors(value)
        if errors:
            raise serializers.ValidationError(errors)
        return value.strip()

    def validate(self, attrs):
        def current(field, default=None):
            return attrs.get(field, getattr(self.instance, field, default))

        password = attrs['ssh_password'] if 'ssh_password' in attrs else getattr(self.instance, 'ssh_password', '')
        if current('ssh_enabled', False):
            if not current('ssh_username', ''):
                raise serializers.ValidationError({'ssh_username': 'Devices need a username to log in with.'})
            if not password and not current('ssh_authorized_keys', '').strip():
                raise serializers.ValidationError(
                    {'ssh_password': 'Set a password or at least one authorised key before enabling SCP/SFTP.'}
                )
        return attrs

    def update(self, instance, validated_data):
        if 'ssh_password' in validated_data:
            password = validated_data.pop('ssh_password')
            instance.ssh_secret = {'password': password} if password else {}
        return super().update(instance, validated_data)


class PushRejectionSerializer(serializers.ModelSerializer):
    class Meta:
        model = PushRejection
        fields = ['id', 'at', 'source_ip', 'protocol', 'reason', 'filename', 'detail']
