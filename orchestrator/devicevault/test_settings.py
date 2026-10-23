"""Settings for the test suite: an explicit throwaway configuration."""

import os

os.environ.update(
    {
        'DV_DEBUG': 'true',
        'DV_SECRET_KEY': 'test-only-secret-key',
        'DV_DB_ENGINE': 'sqlite',
        'DV_DB_NAME': ':memory:',
    }
)

from devicevault.settings import *  # noqa: E402, F403

# Production-strength hashing makes every test user cost ~100ms.
PASSWORD_HASHERS = ['django.contrib.auth.hashers.MD5PasswordHasher']
