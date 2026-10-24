"""Celery application for DeviceVault collection and storage workers.

Start with ``celery -A devicevault_worker.app worker``. The only required
configuration is DV_BROKER_URL and DV_REDIS_URL: the worker starts out
consuming only its own direct queue, registers with the orchestrator, and
consumes the queues of whatever role an administrator approves it for.
"""

from kombu import Exchange, Queue
from redis import Redis

from devicevault_protocol import identity as identity_store
from devicevault_protocol.bus import BusSettings, make_celery_app
from devicevault_protocol.logs import get_logger
from devicevault_protocol.registration import direct_queue_name

__all__ = ['app', 'bus', 'get_logger', 'identity', 'redis_client']

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
