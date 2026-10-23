"""Message bus settings and the Celery app factory.

The broker (RabbitMQ) and Redis endpoints are the only settings a worker needs.
"""

from dataclasses import dataclass

from celery import Celery

from devicevault_protocol.env import env_str


@dataclass(frozen=True)
class BusSettings:
    broker_url: str
    redis_url: str
    result_backend: str

    @classmethod
    def from_env(cls) -> BusSettings:
        redis_url = env_str('DV_REDIS_URL', 'redis://localhost:6379/0')
        return cls(
            broker_url=env_str('DV_BROKER_URL', 'amqp://guest:guest@localhost:5672//'),
            redis_url=redis_url,
            result_backend=env_str('DV_RESULT_BACKEND', redis_url),
        )


def make_celery_app(name: str, settings: BusSettings | None = None, *, imports: tuple[str, ...] = ()) -> Celery:
    settings = settings or BusSettings.from_env()
    app = Celery(name, broker=settings.broker_url, backend=settings.result_backend)
    app.conf.update(
        imports=imports,
        task_serializer='json',
        result_serializer='json',
        accept_content=['json'],
        broker_connection_retry_on_startup=True,
        worker_hijack_root_logger=False,
    )
    return app
