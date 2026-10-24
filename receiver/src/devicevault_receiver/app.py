"""Process-wide state: bus settings, identity, the Celery app used to send events, Redis.

A receiver is not a Celery worker: it consumes nothing but its control queue
(through the registration agent) and only sends tasks.
"""

from redis import Redis

from devicevault_protocol import identity as identity_store
from devicevault_protocol.bus import BusSettings, make_celery_app
from devicevault_protocol.logs import get_logger

__all__ = ['app', 'bus', 'get_logger', 'identity', 'redis_client']

bus = BusSettings.from_env()
identity = identity_store.load_or_create()
app = make_celery_app('devicevault-receiver', bus)
redis_client = Redis.from_url(bus.redis_url)
