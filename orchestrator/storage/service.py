"""Talking to a storage target's workers (see devicevault_worker.storage.tasks)."""

from typing import Any

from core import keys
from core.models import Worker
from core.signing import sign_task
from devicevault.celery import app as celery_app
from devicevault_protocol.names import CHECK_TASK
from devicevault_protocol.registration import ROLE_STORAGE, STATUS_APPROVED
from storage.models import StorageTarget


class TargetUnavailable(Exception):
    """No storage worker answered, or it reported a failure."""


def target_workers(target: StorageTarget) -> list[Worker]:
    """The approved storage workers serving ``target``."""
    return list(target.workers.filter(status=STATUS_APPROVED, role=ROLE_STORAGE))


def target_spec(target: StorageTarget, **fields: Any) -> dict[str, Any]:
    """Task parameters for ``target``: its driver plus its settings, sealed to its workers when required."""
    spec = {'target': {'id': str(target.id), 'driver': target.driver}, **fields}
    keys.add_secret(spec, 'config', target.config, target_workers(target))
    return spec


def ask(target: StorageTarget, task: str, spec: dict[str, Any], *, timeout: int = 60) -> dict[str, Any]:
    """Send a request/response storage task to ``target``'s queue and return the successful result."""
    try:
        result = celery_app.send_task(task, args=[sign_task(spec)], queue=target.queue).get(timeout=timeout)
    except Exception as exc:  # timeouts and broker errors alike
        raise TargetUnavailable(f'no storage worker of "{target.name}" answered: {exc}') from exc
    if result.get('status') != 'success':
        raise TargetUnavailable(result.get('error') or 'the storage worker reported a failure')
    return result


def check_target(target: StorageTarget, *, timeout: int = 30) -> dict[str, Any]:
    """Ask one of the target's workers to verify its settings: ``{"message", "worker"}``."""
    if not target_workers(target):
        raise TargetUnavailable(f'"{target.name}" has no approved storage worker')
    result = ask(target, CHECK_TASK, target_spec(target), timeout=timeout)
    worker = Worker.objects.filter(pk=result.get('worker_id')).first()
    return {'message': result.get('message', ''), 'worker': worker.name if worker else ''}
