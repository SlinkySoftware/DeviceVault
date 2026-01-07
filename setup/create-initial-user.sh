#!/usr/bin/env bash
echo "This script has been renamed to create-initial-configuration.sh. Forwarding to the new script."
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
"$SCRIPT_DIR/create-initial-configuration.sh" "$@"
