
import os, yaml
from pathlib import Path
BASE_DIR = Path(__file__).resolve().parent.parent
SECRET_KEY = os.environ.get('DEVICEVAULT_SECRET_KEY', 'dev-secret')
DEBUG = True
ALLOWED_HOSTS = ['*']
INSTALLED_APPS = [
 'django.contrib.admin','django.contrib.auth','django.contrib.contenttypes','django.contrib.sessions','django.contrib.messages','django.contrib.staticfiles',
 'rest_framework','rest_framework.authtoken','corsheaders','dv_user','dv_devices','dv_backups','core','devices','backups','credentials','locations','policies','audit','api'
]
MIDDLEWARE = ['corsheaders.middleware.CorsMiddleware','django.middleware.security.SecurityMiddleware','django.contrib.sessions.middleware.SessionMiddleware','django.middleware.common.CommonMiddleware','django.middleware.csrf.CsrfViewMiddleware','django.contrib.auth.middleware.AuthenticationMiddleware','django.contrib.messages.middleware.MessageMiddleware','django.middleware.clickjacking.XFrameOptionsMiddleware']
ROOT_URLCONF = 'devicevault.urls'
TEMPLATES = [{'BACKEND':'django.template.backends.django.DjangoTemplates','DIRS':[BASE_DIR/'templates'],'APP_DIRS':True,'OPTIONS':{'context_processors':['django.template.context_processors.debug','django.template.context_processors.request','django.contrib.auth.context_processors.auth','django.contrib.messages.context_processors.messages']}}]
WSGI_APPLICATION = 'devicevault.wsgi.application'
CONFIG_PATH = os.environ.get('DEVICEVAULT_CONFIG', str(BASE_DIR / 'config' / 'config.yaml'))
if os.path.exists(CONFIG_PATH):
    with open(CONFIG_PATH) as f:
        cfg = yaml.safe_load(f) or {}
else:
    cfg = {}
DB_CFG = cfg.get('database', {})
ENGINE = DB_CFG.get('engine','sqlite')
if ENGINE=='sqlite':
    DATABASES={'default':{'ENGINE':'django.db.backends.sqlite3','NAME':DB_CFG.get('name', str(BASE_DIR/'devicevault.sqlite3'))}}
elif ENGINE=='postgres':
    DATABASES={'default':{'ENGINE':'django.db.backends.postgresql','NAME':DB_CFG.get('name','devicevault'),'USER':DB_CFG.get('user',''),'PASSWORD':DB_CFG.get('password',''),'HOST':DB_CFG.get('host','localhost'),'PORT':DB_CFG.get('port','5432')}}
elif ENGINE=='mysql':
    DATABASES={'default':{'ENGINE':'django.db.backends.mysql','NAME':DB_CFG.get('name','devicevault'),'USER':DB_CFG.get('user',''),'PASSWORD':DB_CFG.get('password',''),'HOST':DB_CFG.get('host','localhost'),'PORT':DB_CFG.get('port','3306')}}
LANGUAGE_CODE = 'en-us'
TIME_ZONE = 'Australia/Melbourne'
USE_I18N = True
USE_TZ = True
STATIC_URL = '/static/'
CORS_ALLOW_ALL_ORIGINS = True
CORS_ALLOW_CREDENTIALS = True
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
