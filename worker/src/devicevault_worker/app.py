"""Celery application for DeviceVault collection and storage workers.

Start with ``celery -A devicevault_worker.app worker``. The only required
configuration is DV_BROKER_URL and DV_REDIS_URL: the worker starts out
consuming only its own direct queue, registers with the orchestrator, and
consumes the queues of whatever role an administrator approves it for.
"""

import logging

from kombu import Exchange, Queue
from pythonjsonlogger.json import JsonFormatter
from redis import Redis

from devicevault_protocol.bus import BusSettings, make_celery_app
from devicevault_protocol.env import env_str
from devicevault_protocol.registration import direct_queue_name
from devicevault_worker import identity as identity_store

bus = BusSettings.from_env()
identity = identity_store.load_or_create()

# Auto-deleted so queues of decommissioned workers don't linger on the broker.
direct_queue = Queue(
    direct_queue_name(identity.worker_id),
    Exchange(direct_queue_name(identity.worker_id)),
    routing_key=direct_queue_name(identity.worker_id),
    durable=False,
    auto_delete=True,
)

app = make_celery_app(
    'devicevault-worker',
    bus,
    imports=(
        'devicevault_worker.collect',
        'devicevault_worker.storage.tasks',
        'devicevault_worker.agent',
    ),
)
app.conf.update(task_queues=[direct_queue], task_default_queue=direct_queue.name)

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
