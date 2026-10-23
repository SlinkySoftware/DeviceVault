import pytest
from django.core.management import execute_from_command_line

from core import keys, signing

LOADERS = (signing.signing_key, keys.data_keys, keys.vault)


@pytest.fixture
def fresh_keys():
    for load in LOADERS:
        load.cache_clear()
    yield
    for load in LOADERS:
        load.cache_clear()


def test_keys_can_be_generated_before_any_are_configured(settings, fresh_keys, capsys):
    """Without keys and without a database (the test has no db fixture), as on a fresh install."""
    settings.DEVICEVAULT_SIGNING_KEY = settings.DEVICEVAULT_DATA_KEYS = settings.DEVICEVAULT_VAULT_KEYS = ''
    # As from a shell, which (unlike call_command) runs the system checks.
    execute_from_command_line(['manage.py', 'generate_keys', '--kid', 'k1'])

    generated = dict(line.split('=', 1) for line in capsys.readouterr().out.splitlines())
    assert set(generated) == {'DV_SIGNING_KEY', 'DV_DATA_KEYS', 'DV_VAULT_KEYS'}
    settings.DEVICEVAULT_SIGNING_KEY = generated['DV_SIGNING_KEY']
    settings.DEVICEVAULT_DATA_KEYS = generated['DV_DATA_KEYS']
    settings.DEVICEVAULT_VAULT_KEYS = generated['DV_VAULT_KEYS']
    for load in LOADERS:
        load()
