"""Tell receivers when the set of push-enabled devices changes."""

from django.db.models.signals import post_delete, post_save, pre_save
from django.dispatch import receiver

from devices.models import Device
from devicevault_protocol.push import PUSH_OFF

from .service import receiver_inputs_changed

# What receivers are told about a device; a change to anything else is no news to them.
_FIELDS = ('ip_address', 'push_mode', 'push_filename_pattern', 'enabled', 'inactive_at')


def _pushing(values: dict) -> bool:
    return values['push_mode'] != PUSH_OFF and values['enabled'] and values['inactive_at'] is None


@receiver(pre_save, sender=Device)
def _remember_push_settings(sender, instance, raw=False, **kwargs):
    if raw:
        return
    before = Device.objects.filter(pk=instance.pk).values(*_FIELDS).first() if instance.pk else None
    instance._push_before = before


@receiver(post_save, sender=Device)
def _device_saved(sender, instance, raw=False, **kwargs):
    if raw:
        return
    before = getattr(instance, '_push_before', None)
    after = {field: getattr(instance, field) for field in _FIELDS}
    if before == after:
        return
    if _pushing(after) or (before is not None and _pushing(before)):
        receiver_inputs_changed()


@receiver(post_delete, sender=Device)
def _device_deleted(sender, instance, **kwargs):
    if _pushing({field: getattr(instance, field) for field in _FIELDS}):
        receiver_inputs_changed()
