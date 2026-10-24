#!/bin/sh
# DeviceVault worker entrypoint.
#
# Required: DV_BROKER_URL, DV_REDIS_URL. The worker registers with the
# orchestrator and consumes whatever queues an administrator assigns it.
# `dv-worker version` prints the release version.
set -eu

if [ "${1:-}" = version ]; then
    exec python -m devicevault_protocol.version
fi

if [ "$#" -gt 0 ]; then
    exec "$@"
fi

exec celery -A devicevault_worker.app worker \
    --hostname="${DV_WORKER_NAME:-worker}@%h" \
    --concurrency="${DV_WORKER_CONCURRENCY:-2}" \
    --max-tasks-per-child=100 \
    --loglevel="${DV_LOG_LEVEL:-INFO}"
