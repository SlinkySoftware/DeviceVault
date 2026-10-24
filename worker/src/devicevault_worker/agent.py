"""The worker's registration agent (see ``devicevault_protocol.agent``).

Runs as a thread in the main Celery worker process (started on
``worker_ready``) and applies assignments by adding and cancelling Celery
queue consumers, so the worker consumes only the queues of its approved role.
"""

from typing import Any

from celery.signals import worker_ready, worker_shutdown

from devicevault_protocol.agent import RegistrationAgent
from devicevault_protocol.version import version
from devicevault_worker.app import app, bus, identity


def capabilities() -> dict[str, Any]:
    """What this worker can do; the orchestrator builds its catalogues from these."""
    from devicevault_worker.drivers import list_drivers
    from devicevault_worker.storage import drivers as storage

    return {
        'collector_drivers': [driver.describe() for driver in list_drivers()],
        'storage_drivers': [driver.describe() for driver in storage.list_drivers()],
    }


class WorkerAgent(RegistrationAgent):
    def __init__(self, *, celery_hostname: str, control, **kwargs):
        super().__init__(
            name=celery_hostname.split('@', 1)[0],
            celery_hostname=celery_hostname,
            capabilities=capabilities(),
            version=version(),
            **kwargs,
        )
        self._control = control
        self.queues: set[str] = set()

    def apply(self, payload: dict[str, Any], approved: bool) -> None:
        desired = {str(q) for q in payload.get('queues') or []} if approved else set()
        destination = [self.celery_hostname]
        for queue in sorted(desired - self.queues):
            self._control.add_consumer(queue, destination=destination, reply=True, timeout=10)
            self.queues.add(queue)
        for queue in sorted(self.queues - desired):
            self._control.cancel_consumer(queue, destination=destination, reply=True, timeout=10)
            self.queues.discard(queue)

    def report(self) -> dict[str, Any]:
        return {'queues': sorted(self.queues)}


_agent: WorkerAgent | None = None


@worker_ready.connect
def _start_agent(sender=None, **_kwargs) -> None:
    global _agent
    if sender is None or _agent is not None:
        return
    _agent = WorkerAgent(
        identity=identity,
        celery_hostname=sender.hostname,
        control=app.control,
        broker_url=bus.broker_url,
        send_task=app.send_task,
    )
    _agent.log_identity()
    _agent.start()


@worker_shutdown.connect
def _stop_agent(**_kwargs) -> None:
    if _agent is not None:
        _agent.stop()
