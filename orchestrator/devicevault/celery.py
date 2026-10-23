"""Celery app for the orchestrator.

The API and result consumers use it to send tasks to workers by name. The
`events` process runs it as a worker on ORCHESTRATOR_QUEUE, executing the
tasks in core.tasks (with Django set up by Celery's Django fixup).
"""

import os

from devicevault_protocol.bus import BusSettings, make_celery_app
from devicevault_protocol.registration import ORCHESTRATOR_QUEUE

os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'devicevault.settings')

bus = BusSettings.from_env()
app = make_celery_app('devicevault-orchestrator', bus, imports=('core.tasks',))
app.conf.update(task_default_queue=ORCHESTRATOR_QUEUE)
