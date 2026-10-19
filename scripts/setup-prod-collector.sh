#!/usr/bin/env bash

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

GROUP_ID="${1:-default}"
ORCHESTRATOR_HOST="${2:-node1.internal}"

echo "WARNING: setup-prod-collector.sh is deprecated. Use setup-prod-collector-worker.sh instead." >&2
echo "WARNING: separate Redis/RabbitMQ host arguments are no longer used; configure endpoints via the new script if they differ from the orchestrator host." >&2

exec "$SCRIPT_DIR/setup-prod-collector-worker.sh" \
    --orchestrator-host "$ORCHESTRATOR_HOST" \
    --collector-queues "collector.group.$GROUP_ID"
