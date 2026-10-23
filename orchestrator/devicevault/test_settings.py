"""Settings for the test suite: an explicit throwaway configuration."""

import os

os.environ.update(
    {
        'DV_DEBUG': 'true',
        'DV_SECRET_KEY': 'test-only-secret-key',
        'DV_DB_ENGINE': 'sqlite',
        'DV_DB_NAME': ':memory:',
        # Test-only signing key (32 zero-padded bytes); never use outside tests.
        'DV_SIGNING_KEY': 'dGVzdC1vbmx5LXNpZ25pbmcta2V5LTMyLWJ5dGVzISE=',
    }
)

from devicevault.settings import *  # noqa: E402, F403

# Production-strength hashing makes every test user cost ~100ms.
PASSWORD_HASHERS = ['django.contrib.auth.hashers.MD5PasswordHasher']
