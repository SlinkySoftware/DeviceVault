# DeviceVault - A comprehensive network device backup management application with web interface for user and admin access and backend component for automated backup collection.
# Copyright (C) 2026, Slinky Software
#
# This program is free software: you can redistribute it and/or modify
# it under the terms of the GNU General Public License as published by
# the Free Software Foundation, either version 3 of the License, or
# (at your option) any later version.
#
# This program is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
# GNU General Public License for more details.
#
# You should have received a copy of the GNU General Public License
# along with this program.  If not, see <http://www.gnu.org/licenses/>.

# All configuration comes from DV_* environment variables; each also accepts
# <NAME>_FILE for Docker secrets. See deploy/orchestrator/orchestrator.env.example.

from pathlib import Path

from devicevault_protocol.bus import BusSettings
from devicevault_protocol.env import ConfigError, env_bool, env_int, env_list, env_str

BASE_DIR = Path(__file__).resolve().parent.parent
DATA_DIR = Path(env_str('DV_DATA_DIR', str(BASE_DIR / 'var')))

DEBUG = env_bool('DV_DEBUG', False)
SECRET_KEY = env_str('DV_SECRET_KEY')
if not SECRET_KEY:
    if not DEBUG:
        raise ConfigError('DV_SECRET_KEY must be set when DV_DEBUG is false')
    SECRET_KEY = 'insecure-development-key'

ALLOWED_HOSTS = env_list('DV_ALLOWED_HOSTS', ['*'] if DEBUG else [])
CSRF_TRUSTED_ORIGINS = env_list('DV_CSRF_TRUSTED_ORIGINS')

INSTALLED_APPS = [
    'django.contrib.auth',
    'django.contrib.contenttypes',
    'django.contrib.sessions',
    'django.contrib.staticfiles',
    'rest_framework',
    'core',
    'accounts',
    'devices',
    'backups',
    'credentials',
    'storage',
    'monitoring',
    'policies',
    'push',
    'search',
    'audit',
    'api',
]
MIDDLEWARE = [
    'django.middleware.security.SecurityMiddleware',
    'django.contrib.sessions.middleware.SessionMiddleware',
    'django.middleware.common.CommonMiddleware',
    'django.middleware.csrf.CsrfViewMiddleware',
    'django.contrib.auth.middleware.AuthenticationMiddleware',
    'accounts.sessions.SessionTimeoutMiddleware',
    'django.middleware.clickjacking.XFrameOptionsMiddleware',
]
if not DEBUG:
    # Serves collected static files (DRF) in the image; runserver does it in DEBUG.
    MIDDLEWARE.insert(1, 'whitenoise.middleware.WhiteNoiseMiddleware')
ROOT_URLCONF = 'devicevault.urls'
TEMPLATES = [
    {
        'BACKEND': 'django.template.backends.django.DjangoTemplates',
        'DIRS': [BASE_DIR / 'templates'],
        'APP_DIRS': True,
        'OPTIONS': {
            'context_processors': [
                'django.template.context_processors.debug',
                'django.template.context_processors.request',
                'django.contrib.auth.context_processors.auth',
            ]
        },
    }
]
WSGI_APPLICATION = 'devicevault.wsgi.application'

DB_ENGINE = env_str('DV_DB_ENGINE', 'sqlite').strip().lower()
if DB_ENGINE == 'sqlite':
    DATABASES = {
        'default': {
            'ENGINE': 'django.db.backends.sqlite3',
            'NAME': env_str('DV_DB_NAME', str(DATA_DIR / 'devicevault.sqlite3')),
            'OPTIONS': {
                # Several orchestrator processes share one SQLite file.
                'transaction_mode': 'IMMEDIATE',
                'timeout': 20,
                'init_command': 'PRAGMA journal_mode=WAL; PRAGMA synchronous=NORMAL;',
            },
        }
    }
elif DB_ENGINE == 'postgres':
    DATABASES = {
        'default': {
            'ENGINE': 'django.db.backends.postgresql',
            'NAME': env_str('DV_DB_NAME', 'devicevault'),
            'USER': env_str('DV_DB_USER', 'devicevault'),
            'PASSWORD': env_str('DV_DB_PASSWORD', ''),
            'HOST': env_str('DV_DB_HOST', 'localhost'),
            'PORT': env_int('DV_DB_PORT', 5432),
            'CONN_MAX_AGE': 60,
            'CONN_HEALTH_CHECKS': True,
        }
    }
    # Several hosts (a replicated cluster): connect to whichever accepts writes.
    if ',' in DATABASES['default']['HOST']:
        DATABASES['default']['OPTIONS'] = {'target_session_attrs': 'read-write'}
else:
    raise ConfigError(f'DV_DB_ENGINE must be sqlite or postgres, got {DB_ENGINE!r}')

LANGUAGE_CODE = 'en-us'
# Display timezone; the database always stores UTC.
DEVICEVAULT_DISPLAY_TIMEZONE = env_str('DV_TIMEZONE', 'UTC')
TIME_ZONE = 'UTC'
USE_I18N = True
USE_TZ = True

STATIC_URL = '/static/'
STATIC_ROOT = BASE_DIR / 'staticfiles'
STORAGES = {
    'default': {'BACKEND': 'django.core.files.storage.FileSystemStorage'},
    'staticfiles': {'BACKEND': 'whitenoise.storage.CompressedManifestStaticFilesStorage'},
}

# Behind nginx, which terminates TLS.
SECURE_PROXY_SSL_HEADER = ('HTTP_X_FORWARDED_PROTO', 'https')
USE_X_FORWARDED_HOST = True

# Server-side sessions in the database (shared by every orchestrator node), used
# by the UI and the API alike. See accounts.sessions for the timeouts.
SESSION_ENGINE = 'django.contrib.sessions.backends.db'
SESSION_COOKIE_HTTPONLY = True
SESSION_COOKIE_SAMESITE = 'Lax'  # sent on the redirect back from an identity provider
SESSION_COOKIE_SECURE = not DEBUG
CSRF_COOKIE_SECURE = not DEBUG
CSRF_COOKIE_HTTPONLY = False  # the UI reads it and echoes it in X-CSRFToken
DEVICEVAULT_SESSION_IDLE_MIN = env_int('DV_SESSION_IDLE_MIN', 60, minimum=1)
DEVICEVAULT_SESSION_MAX_HOURS = env_int('DV_SESSION_MAX_HOURS', 12, minimum=1)
SESSION_COOKIE_AGE = DEVICEVAULT_SESSION_MAX_HOURS * 3600
DEVICEVAULT_LOGIN_MAX_FAILURES = env_int('DV_LOGIN_MAX_FAILURES', 5, minimum=1)
DEVICEVAULT_LOGIN_LOCKOUT_MIN = env_int('DV_LOGIN_LOCKOUT_MIN', 15, minimum=1)

AUTH_PASSWORD_VALIDATORS = [
    {'NAME': 'django.contrib.auth.password_validation.UserAttributeSimilarityValidator'},
    {'NAME': 'django.contrib.auth.password_validation.MinimumLengthValidator', 'OPTIONS': {'min_length': 10}},
    {'NAME': 'django.contrib.auth.password_validation.CommonPasswordValidator'},
    {'NAME': 'django.contrib.auth.password_validation.NumericPasswordValidator'},
]

REST_FRAMEWORK = {
    'DEFAULT_AUTHENTICATION_CLASSES': ['accounts.authentication.SessionAuthentication'],
    # A safety net only: every view states its own permission classes (accounts.access).
    'DEFAULT_PERMISSION_CLASSES': ['rest_framework.permissions.IsAuthenticated'],
    'EXCEPTION_HANDLER': 'api.exceptions.exception_handler',
}

LOGGING = {
    'version': 1,
    'disable_existing_loggers': False,
    'handlers': {'console': {'class': 'logging.StreamHandler'}},
    'root': {'handlers': ['console'], 'level': env_str('DV_LOG_LEVEL', 'INFO')},
}

DEVICEVAULT_BUS = BusSettings.from_env()
DEVICEVAULT_LOCAL_AUTH_ENABLED = env_bool('DV_LOCAL_AUTH_ENABLED', True)
DEVICEVAULT_WORKER_ONLINE_TIMEOUT_SEC = env_int('DV_WORKER_ONLINE_TIMEOUT_SEC', 90, minimum=1)
DEVICEVAULT_COLLECT_TIMEOUT_SEC = env_int('DV_COLLECT_TIMEOUT_SEC', 120, minimum=5)
DEVICEVAULT_JOB_TIMEOUT_MIN = env_int('DV_JOB_TIMEOUT_MIN', 120, minimum=1)
DEVICEVAULT_SCHEDULER_INTERVAL_SEC = env_int('DV_SCHEDULER_INTERVAL_SEC', 30, minimum=5)
DEVICEVAULT_RETENTION_INTERVAL_MIN = env_int('DV_RETENTION_INTERVAL_MIN', 60, minimum=1)
# Config search (search app): indexes decrypted configuration in the database, so it is opt-in.
DEVICEVAULT_CONFIG_SEARCH = env_bool('DV_CONFIG_SEARCH', False)
# Ed25519 key that signs everything sent to workers; see core.signing.
DEVICEVAULT_SIGNING_KEY = env_str('DV_SIGNING_KEY')
# Encryption keys; see core.keys. Data keys encrypt secrets at rest (always on).
DEVICEVAULT_DATA_KEYS = env_str('DV_DATA_KEYS')
# Payload encryption of backups and secrets sent to workers: off for development
# (queues and Redis stay readable), on for deployments.
DEVICEVAULT_PAYLOAD_ENCRYPTION = env_bool('DV_PAYLOAD_ENCRYPTION', False)
DEVICEVAULT_VAULT_KEYS = env_str('DV_VAULT_KEYS')
