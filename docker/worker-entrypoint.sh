#!/bin/sh
# DeviceVault worker entrypoint.
#
# Required: DV_BROKER_URL, DV_REDIS_URL.
# Interim (until workers receive their assignment from the orchestrator in
# phase 4): DV_WORKER_QUEUES selects the queues this worker consumes.
set -eu

if [ "$#" -gt 0 ]; then
    exec "$@"
fi

: "${DV_WORKER_QUEUES:?DV_WORKER_QUEUES must list the queues to consume (interim until phase 4)}"

exec celery -A devicevault_worker.app worker \
    --queues="$DV_WORKER_QUEUES" \
    --hostname="${DV_WORKER_NAME:-worker}@%h" \
    --concurrency="${DV_WORKER_CONCURRENCY:-2}" \
    --max-tasks-per-child=100 \
    --loglevel="${DV_LOG_LEVEL:-INFO}"
