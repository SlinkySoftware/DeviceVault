#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$SCRIPT_DIR/.."
cd "$REPO_ROOT/backend"

PYTHON=${PYTHON:-python3}

echo "Running migrations before seeding demo data..."
$PYTHON manage.py migrate --run-syncdb

echo "Populating demonstration/sample data..."
# seed_data.py is executable and sets up Django environment
$PYTHON seed_data.py

echo "Demo data populated."
