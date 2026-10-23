"""Celery app the orchestrator uses to dispatch tasks to workers.

The orchestrator never executes worker tasks; it only sends them by name.
"""

from devicevault_protocol.bus import BusSettings, make_celery_app

bus = BusSettings.from_env()
app = make_celery_app('devicevault-orchestrator', bus)
