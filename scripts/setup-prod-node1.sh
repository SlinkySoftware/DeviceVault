#!/usr/bin/env bash

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

echo "WARNING: setup-prod-node1.sh is deprecated. Use setup-prod-orchestrator-primary.sh instead." >&2
exec "$SCRIPT_DIR/setup-prod-orchestrator-primary.sh" "$@"
