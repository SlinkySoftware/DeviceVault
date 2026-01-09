import os
from celery import Celery

try:
    # If Django settings are available, prefer them for configuration
    os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'devicevault.settings')
    from django.conf import settings as django_settings
except Exception:
    django_settings = None

# Broker and backend: prefer Django settings -> env vars -> sensible defaults
if django_settings is not None:
    BROKER = getattr(django_settings, 'CELERY_BROKER_URL', os.environ.get('DEVICEVAULT_BROKER_URL'))
    BACKEND = getattr(django_settings, 'CELERY_RESULT_BACKEND', os.environ.get('DEVICEVAULT_RESULT_BACKEND', BROKER))
    BROKER_API = getattr(django_settings, 'CELERY_BROKER_API', os.environ.get('DEVICEVAULT_BROKER_API', 'http://guest:guest@localhost:15672/api/'))
    REDIS_URL = getattr(django_settings, 'DEVICEVAULT_REDIS_URL', os.environ.get('DEVICEVAULT_REDIS_URL', 'redis://localhost:6379/1'))
    RESULTS_STREAM = getattr(django_settings, 'DEVICEVAULT_RESULTS_STREAM', os.environ.get('DEVICEVAULT_RESULTS_STREAM', 'device:results'))
else:
    BROKER = os.environ.get('DEVICEVAULT_BROKER_URL', 'amqp://guest:guest@localhost:5672//')
    BACKEND = os.environ.get('DEVICEVAULT_RESULT_BACKEND', BROKER)
    BROKER_API = os.environ.get('DEVICEVAULT_BROKER_API', 'http://guest:guest@localhost:15672/api/')
    REDIS_URL = os.environ.get('DEVICEVAULT_REDIS_URL', 'redis://localhost:6379/1')
    RESULTS_STREAM = os.environ.get('DEVICEVAULT_RESULTS_STREAM', 'device:results')

app = Celery('devicevault', broker=BROKER, backend=BACKEND)
app.conf.update(
    broker_api=BROKER_API,
)

# Expose simple values for other modules
__all__ = ['app', 'BROKER', 'BACKEND', 'BROKER_API', 'REDIS_URL', 'RESULTS_STREAM']
