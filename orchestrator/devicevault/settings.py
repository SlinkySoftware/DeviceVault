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

import os
from pathlib import Path

import yaml


BASE_DIR = Path(__file__).resolve().parent.parent


def _env_flag(name, default):
    value = os.environ.get(name)
    if value is None:
        return default
    return value.strip().lower() in {'1', 'true', 'yes', 'on'}


def _env_list(name, default):
    value = os.environ.get(name)
    if value is None:
        return default
    parsed = [item.strip() for item in value.split(',') if item.strip()]
    return parsed or default


CONFIG_PATH = os.environ.get('DEVICEVAULT_CONFIG', str(BASE_DIR / 'config' / 'config.yaml'))
if os.path.exists(CONFIG_PATH):
    with open(CONFIG_PATH, encoding='utf-8') as config_handle:
        cfg = yaml.safe_load(config_handle) or {}
else:
    cfg = {}

SECRET_KEY = os.environ.get(
    'DEVICEVAULT_SECRET_KEY',
    cfg.get('secret_key', 'dev-secret'),
)
DEBUG = _env_flag('DEBUG', cfg.get('debug', True))
ALLOWED_HOSTS = _env_list('ALLOWED_HOSTS', cfg.get('allowed_hosts', ['*']))
INSTALLED_APPS = [
 'django.contrib.admin','django.contrib.auth','django.contrib.contenttypes','django.contrib.sessions','django.contrib.messages','django.contrib.staticfiles',
 'rest_framework','rest_framework.authtoken','corsheaders','core','devices','backups','credentials','locations','policies','audit','api'
]
MIDDLEWARE = ['corsheaders.middleware.CorsMiddleware','django.middleware.security.SecurityMiddleware','django.contrib.sessions.middleware.SessionMiddleware','django.middleware.common.CommonMiddleware','django.middleware.csrf.CsrfViewMiddleware','django.contrib.auth.middleware.AuthenticationMiddleware','django.contrib.messages.middleware.MessageMiddleware','django.middleware.clickjacking.XFrameOptionsMiddleware']
ROOT_URLCONF = 'devicevault.urls'
TEMPLATES = [{'BACKEND':'django.template.backends.django.DjangoTemplates','DIRS':[BASE_DIR/'templates'],'APP_DIRS':True,'OPTIONS':{'context_processors':['django.template.context_processors.debug','django.template.context_processors.request','django.contrib.auth.context_processors.auth','django.contrib.messages.context_processors.messages']}}]
WSGI_APPLICATION = 'devicevault.wsgi.application'

DB_CFG = cfg.get('database', {})
ENGINE = (
    os.environ.get('DEVICEVAULT_DB_ENGINE')
    or DB_CFG.get('engine')
    or 'sqlite'
).strip().lower()

if ENGINE == 'sqlite':
    DATABASES = {
        'default': {
            'ENGINE': 'django.db.backends.sqlite3',
            'NAME': os.environ.get(
                'DEVICEVAULT_DB_NAME',
                DB_CFG.get('name', str(BASE_DIR / 'devicevault.sqlite3')),
            ),
        }
    }
elif ENGINE == 'postgres':
    DATABASES = {
        'default': {
            'ENGINE': 'django.db.backends.postgresql',
            'NAME': os.environ.get(
                'DEVICEVAULT_DB_NAME',
                os.environ.get('POSTGRES_DB', DB_CFG.get('name', 'devicevault')),
            ),
            'USER': os.environ.get(
                'DEVICEVAULT_DB_USER',
                os.environ.get('POSTGRES_USER', DB_CFG.get('user', '')),
            ),
            'PASSWORD': os.environ.get(
                'DEVICEVAULT_DB_PASSWORD',
                os.environ.get('POSTGRES_PASSWORD', DB_CFG.get('password', '')),
            ),
            'HOST': os.environ.get(
                'DEVICEVAULT_DB_HOST',
                os.environ.get('POSTGRES_HOST', DB_CFG.get('host', 'localhost')),
            ),
            'PORT': os.environ.get(
                'DEVICEVAULT_DB_PORT',
                os.environ.get('POSTGRES_PORT', DB_CFG.get('port', '5432')),
            ),
        }
    }
else:
    raise ValueError(f'Unsupported database engine: {ENGINE}')
LANGUAGE_CODE = 'en-us'
# Application timezone for display - read from config.yaml or default to Australia/Sydney
DEVICEVAULT_DISPLAY_TIMEZONE = cfg.get('timezone', 'Australia/Sydney')
# Django timezone - always UTC for database storage
TIME_ZONE = 'UTC'
USE_I18N = True
USE_TZ = True
STATIC_URL = '/static/'
CORS_ALLOW_ALL_ORIGINS = _env_flag('DEVICEVAULT_CORS_ALLOW_ALL_ORIGINS', True)
CORS_ALLOW_CREDENTIALS = _env_flag('DEVICEVAULT_CORS_ALLOW_CREDENTIALS', True)

_cors_allowed_origins_raw = os.environ.get('DEVICEVAULT_CORS_ALLOWED_ORIGINS', '')
if _cors_allowed_origins_raw:
    CORS_ALLOWED_ORIGINS = [
        origin.strip().rstrip('/')
        for origin in _cors_allowed_origins_raw.split(',')
        if origin.strip()
    ]
elif not CORS_ALLOW_ALL_ORIGINS:
    CORS_ALLOWED_ORIGINS = [
        'http://localhost:9000',
        'http://127.0.0.1:9000',
    ]
REST_FRAMEWORK = {
    'DEFAULT_AUTHENTICATION_CLASSES': [
        'rest_framework.authentication.TokenAuthentication',
        'rest_framework.authentication.SessionAuthentication',
        'rest_framework.authentication.BasicAuthentication'
    ],
    'DEFAULT_PERMISSION_CLASSES': [
        'rest_framework.permissions.IsAuthenticated'
    ]
}

# Celery configuration: prefer explicit env var, then config.yaml 'celery' section, then sensible defaults
CELERY_BROKER_URL = os.environ.get(
    'DEVICEVAULT_BROKER_URL',
    cfg.get('celery', {}).get('broker', 'amqp://guest:guest@localhost:5672//')
)
DEVICEVAULT_REDIS_URL = os.environ.get(
    'DEVICEVAULT_REDIS_URL',
    cfg.get('redis', {}).get('url', 'redis://localhost:6379/1')
)
CELERY_RESULT_BACKEND = os.environ.get(
    'DEVICEVAULT_RESULT_BACKEND',
    cfg.get('celery', {}).get('result_backend', DEVICEVAULT_REDIS_URL)
)
# RabbitMQ management API for Flower - uses HTTP port (15672 by default)
CELERY_BROKER_API = os.environ.get(
    'DEVICEVAULT_BROKER_API',
    cfg.get('celery', {}).get('broker_api', 'http://guest:guest@localhost:15672/api/')
)
DEVICEVAULT_RESULTS_STREAM = cfg.get('results_stream', os.environ.get('DEVICEVAULT_RESULTS_STREAM', 'device:results'))
DEVICEVAULT_STORAGE_RESULTS_STREAM = os.environ.get(
    'DEVICEVAULT_STORAGE_RESULTS_STREAM',
    cfg.get('storage_results_stream', 'storage:results')
)

# Encryption configuration - loaded from config.yaml 'encryption' section / env vars.
# The heavy lifting (key provider init, crypto wrapper) is done lazily in
# crypto.config to keep settings.py import-time fast and fail-safe.
DEVICEVAULT_ENCRYPTION = cfg.get('encryption', {})
