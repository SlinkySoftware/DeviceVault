"""What receivers are told, and keeping them up to date.

Every receiver accepts every push-enabled device, so its assignment lists them
all; any change to that list, or to a receiver's settings, sends receivers a
new assignment version.
"""

from typing import Any

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

    devices = Device.objects.filter(enabled=True).exclude(push_mode=PUSH_OFF).order_by('pk')
    return [
        {'id': d.pk, 'ip': d.ip_address, 'push_mode': d.push_mode, 'filename_pattern': d.push_filename_pattern}
        for d in devices
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


def bump_receivers() -> None:
    """Send every receiver a new assignment once the current transaction commits."""
    from core.workers import update_assignment

    def bump():
        for worker in receivers():
            update_assignment(worker)

    transaction.on_commit(bump)
