"""Celery application for DeviceVault collection and storage workers.

Start with ``celery -A devicevault_worker.app worker -Q <queues>``. The only
required configuration is DV_BROKER_URL and DV_REDIS_URL.
"""

import logging

from pythonjsonlogger.json import JsonFormatter
from redis import Redis

from devicevault_protocol.bus import BusSettings, make_celery_app
from devicevault_protocol.env import env_str

bus = BusSettings.from_env()

app = make_celery_app(
    'devicevault-worker',
    bus,
    imports=(
        'devicevault_worker.collect',
        'devicevault_worker.storage.tasks',
        'devicevault_worker.presence',
    ),
)

redis_client = Redis.from_url(bus.redis_url)


def get_logger(name: str) -> logging.Logger:
    """Return a logger that emits structured JSON to stderr."""
    logger = logging.getLogger(name)
    if not logger.handlers:
        handler = logging.StreamHandler()
        handler.setFormatter(JsonFormatter('%(asctime)s %(levelname)s %(name)s %(message)s'))
        logger.addHandler(handler)
        logger.setLevel(env_str('DV_LOG_LEVEL', 'INFO'))
        logger.propagate = False
    return logger
