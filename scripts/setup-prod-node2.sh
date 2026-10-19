#!/usr/bin/env bash

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

PRIMARY_HOST="${1:-}"
DB_PASSWORD="${2:-}"
REPLICATION_PASSWORD="${3:-}"
RABBITMQ_COOKIE="${4:-}"
ARGS=()

echo "WARNING: setup-prod-node2.sh is deprecated. Use setup-prod-orchestrator-backup.sh instead." >&2
if [[ -n "$PRIMARY_HOST" ]]; then
    ARGS+=(--primary-host "$PRIMARY_HOST")
fi
if [[ -n "$DB_PASSWORD" ]]; then
    ARGS+=(--db-password "$DB_PASSWORD")
fi
if [[ -n "$REPLICATION_PASSWORD" ]]; then
    ARGS+=(--replication-password "$REPLICATION_PASSWORD")
fi
if [[ -n "$RABBITMQ_COOKIE" ]]; then
    ARGS+=(--rabbitmq-cookie "$RABBITMQ_COOKIE")
fi

exec "$SCRIPT_DIR/setup-prod-orchestrator-backup.sh" "${ARGS[@]}"
