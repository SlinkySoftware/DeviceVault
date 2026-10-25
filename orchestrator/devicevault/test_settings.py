"""Settings for the test suite: an explicit throwaway configuration."""

import os

os.environ.update(
    {
        'DV_DEBUG': 'true',
        'DV_SECRET_KEY': 'test-only-secret-key',
        # Test-only keys; never use outside tests. Payload encryption stays off unless a test turns it on.
        'DV_SIGNING_KEY': 'dGVzdC1vbmx5LXNpZ25pbmcta2V5LTMyLWJ5dGVzISE=',
        'DV_DATA_KEYS': 'test=dGVzdC1vbmx5LWRhdGEta2V5LTMyLWJ5dGVzISEhISE=',
        'DV_VAULT_KEYS': 'test=dGVzdC1vbmx5LXZhdWx0LWtleS0zMi1ieXRlcyEhISE=',
    }
)

# ``make test-postgres`` runs the suite against a throwaway PostgreSQL (DV_TEST_POSTGRES_HOST).
if os.environ.get('DV_TEST_POSTGRES_HOST'):
    os.environ.update(
        {
            'DV_DB_ENGINE': 'postgres',
            'DV_DB_HOST': os.environ['DV_TEST_POSTGRES_HOST'],
            'DV_DB_NAME': 'devicevault',
            'DV_DB_USER': 'devicevault',
            'DV_DB_PASSWORD': 'test-only',
        }
    )
else:
    os.environ.update({'DV_DB_ENGINE': 'sqlite', 'DV_DB_NAME': ':memory:'})

from devicevault.settings import *  # noqa: E402, F403

# Production-strength hashing makes every test user cost ~100ms.
PASSWORD_HASHERS = ['django.contrib.auth.hashers.MD5PasswordHasher']
