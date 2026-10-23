"""Startup checks for the orchestrator's keys (run by migrate, runserver and ``manage.py check``)."""

from django.conf import settings
from django.core import checks
from django.core.exceptions import ImproperlyConfigured


@checks.register(checks.Tags.security)
def check_keys(app_configs=None, **kwargs):
    from core import keys, signing

    problems = []
    loaders = [('DV_SIGNING_KEY', signing.signing_key), ('DV_DATA_KEYS', keys.data_keys)]
    if settings.DEVICEVAULT_PAYLOAD_ENCRYPTION:
        loaders.append(('DV_VAULT_KEYS', keys.vault))
    for name, load in loaders:
        try:
            load()
        except ImproperlyConfigured as exc:
            problems.append(checks.Error(str(exc), id=f'devicevault.E{len(problems) + 1:03d}', obj=name))
    if not settings.DEVICEVAULT_PAYLOAD_ENCRYPTION and not settings.DEBUG:
        problems.append(
            checks.Warning(
                'Payload encryption is off: backups and device credentials cross RabbitMQ and Redis in plaintext.',
                hint='Set DV_PAYLOAD_ENCRYPTION=true and DV_VAULT_KEYS (manage.py generate_keys).',
                id='devicevault.W001',
            )
        )
    return problems
