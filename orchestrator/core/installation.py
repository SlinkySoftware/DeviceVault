"""Every orchestrator node of a deployment must use the same database.

Each database holds a random installation id, and ``migrate`` claims the
message bus for it in Redis. A node whose database has another id (typically
a second node given its own SQLite file) refuses to start, rather than
splitting workers and jobs between two databases.
"""

from django.conf import settings
from redis import Redis

from core.models import Installation

CLAIM_KEY = 'dv:orchestrator:installation'


class InstallationMismatch(Exception):
    """Redis is claimed by another database."""


def installation_id() -> str:
    installation = Installation.objects.order_by('created_at').first() or Installation.objects.create()
    return str(installation.id)


def claim(redis: Redis | None = None, *, force: bool = False) -> str:
    """Claim the message bus for this database and return its id, unless another database holds it."""
    redis = redis or Redis.from_url(settings.DEVICEVAULT_BUS.redis_url)
    mine = installation_id()
    if force:
        redis.set(CLAIM_KEY, mine)
    elif not redis.set(CLAIM_KEY, mine, nx=True):
        held = (redis.get(CLAIM_KEY) or b'').decode()
        if held != mine:
            raise InstallationMismatch(
                f'Redis belongs to the orchestrator database {held}, but this database is {mine}. '
                'Every orchestrator node must use the same database, and SQLite allows only one node '
                '(use PostgreSQL for more). If this database deliberately replaces the old one, run '
                '"manage.py claim_installation --force".'
            )
    return mine
