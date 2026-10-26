"""What receivers are told, and keeping them up to date.

Every receiver accepts every push-enabled device, so its assignment lists them
all; any change to that list, or to a receiver's settings, sends receivers a
new assignment version. The same goes for the tokens their monitoring relays
accept (``monitoring.relay``).
"""

from typing import Any

from django.conf import settings as django_settings
from django.db import transaction

from core import keys
from core.models import Worker
from devicevault_protocol.push import PUSH_OFF
from devicevault_protocol.registration import ROLE_RECEIVER, STATUS_APPROVED
from push.models import ReceiverSettings


def receivers():
    return Worker.objects.filter(status=STATUS_APPROVED, role=ROLE_RECEIVER)


def settings_for(worker: Worker) -> ReceiverSettings:
    settings, _ = ReceiverSettings.objects.get_or_create(worker=worker)
    return settings


def push_devices() -> list[dict[str, Any]]:
    """The devices receivers accept pushes from."""
    from devices.models import Device

    devices = Device.objects.filter(enabled=True, inactive_at__isnull=True).exclude(push_mode=PUSH_OFF).order_by('pk')
    return [
        {'id': d.pk, 'ip': d.ip_address, 'push_mode': d.push_mode, 'filename_pattern': d.push_filename_pattern}
        for d in devices
    ]


def relay_tokens() -> list[dict[str, Any]]:
    """The tokens receiver relays accept: digests only, never a secret."""
    from monitoring.snapshots import relay_tokens as live_relay_tokens

    return [
        {
            'prefix': token.prefix,
            'digest': token.digest,
            'owner': token.user_id,
            'expires_at': token.expires_at.isoformat(),
            'allowed_networks': list(token.allowed_networks or []),
        }
        for token in live_relay_tokens()
    ]


def receiver_assignment(worker: Worker) -> dict[str, Any]:
    """The ``receiver`` section of an approved receiver's assignment."""
    settings = settings_for(worker)
    ssh = {
        'enabled': settings.ssh_enabled,
        'port': settings.ssh_port,
        'username': settings.ssh_username,
        'authorized_keys': settings.ssh_authorized_keys,
    }
    keys.add_secret(ssh, 'password', settings.ssh_password, [worker])
    return {
        'bind_address': settings.bind_address or '',
        'max_file_size': settings.max_file_size,
        'ssh': ssh,
        'tftp': {'enabled': settings.tftp_enabled, 'port': settings.tftp_port},
        'monitoring': {
            'enabled': settings.monitoring_enabled,
            'port': settings.monitoring_port,
            'rate': django_settings.DEVICEVAULT_API_TOKEN_RATE,
            'tokens': relay_tokens() if settings.monitoring_enabled else [],
        },
        'devices': push_devices(),
        'encryption': keys.vault_public(),
    }


def needs_update(worker: Worker) -> bool:
    """True if an in-sync receiver reports a vault key other than the current one (the key ring rotated)."""
    reported = (worker.runtime or {}).get('receiver')
    if not isinstance(reported, dict):
        return False
    vault = keys.vault_public()
    return reported.get('vault_kid') != (vault['kid'] if vault else None)


def receiver_inputs_changed() -> None:
    """Something every receiver's assignment holds changed: push-enabled devices, or relay tokens and owners.

    Sends every receiver a new assignment once the current transaction commits.
    """
    from core.workers import update_assignment

    def bump():
        for worker in receivers():
            update_assignment(worker)

    transaction.on_commit(bump)
