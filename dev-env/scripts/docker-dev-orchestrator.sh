#!/bin/bash

set -euo pipefail

LOG_DIR="${DEVICEVAULT_LOG_DIR:-/var/devicevault/logs/orchestrator}"
CONFIG_PATH="${DEVICEVAULT_CONFIG:-/workspace/var/docker-dev/config/backend-config.yaml}"

mkdir -p "$LOG_DIR"

if [ ! -f "$CONFIG_PATH" ]; then
    echo "Missing backend config at $CONFIG_PATH"
    exit 1
fi

echo "Running migrations..."
fixed_icon_migration=0
fixed_device_group_column=0

for _attempt in 1 2 3 4; do
    MIGRATE_LOG="$(mktemp)"
    if python manage.py migrate --run-syncdb --noinput >"$MIGRATE_LOG" 2>&1; then
        cat "$MIGRATE_LOG"
        rm -f "$MIGRATE_LOG"
        break
    fi

    if [ "$fixed_icon_migration" -eq 0 ] && grep -q 'column "icon" of relation "devices_devicetype" already exists' "$MIGRATE_LOG"; then
        echo "Detected duplicate devices icon migration. Applying fake migration for devices.0002_add_icon_field and retrying."
        python manage.py migrate devices 0002_add_icon_field --fake --noinput
        fixed_icon_migration=1
        rm -f "$MIGRATE_LOG"
        continue
    fi

    if [ "$fixed_device_group_column" -eq 0 ] && grep -q 'column "device_group_id" does not exist' "$MIGRATE_LOG"; then
        echo "Detected missing devices.device_group_id column. Creating column and retrying migrations."
        python manage.py shell <<'PY'
from django.db import connection

table = 'devices_device'
with connection.cursor() as cursor:
    existing_tables = set(connection.introspection.table_names())
    if table not in existing_tables:
        raise SystemExit(0)
    columns = [col.name for col in connection.introspection.get_table_description(cursor, table)]
    if 'device_group_id' not in columns:
        cursor.execute('ALTER TABLE devices_device ADD COLUMN device_group_id integer')
PY
        fixed_device_group_column=1
        rm -f "$MIGRATE_LOG"
        continue
    fi

    cat "$MIGRATE_LOG"
    rm -f "$MIGRATE_LOG"
    exit 1
done

echo "Ensuring default admin user exists..."
python manage.py create_admin --username admin --password admin --email admin@example.com

PIDS=()

start_process() {
    local name="$1"
    shift
    local logfile="$LOG_DIR/${name}.log"
    echo "Starting ${name}..."
    (
        exec "$@" >>"$logfile" 2>&1
    ) &
    PIDS+=($!)
}

shutdown() {
    local signal="${1:-TERM}"
    for pid in "${PIDS[@]:-}"; do
        if kill -0 "$pid" >/dev/null 2>&1; then
            kill "-$signal" "$pid" >/dev/null 2>&1 || true
        fi
    done
}

trap 'shutdown TERM; wait || true; exit 0' INT TERM

start_process "django" python manage.py runserver 0.0.0.0:8000
start_process "device-results-consumer" python manage.py consume_device_results
start_process "storage-results-consumer" python manage.py consume_storage_results
start_process "celery-beat" celery -A celery_app beat -l info -s /var/devicevault/logs/orchestrator/celerybeat-schedule

wait -n "${PIDS[@]}"
status=$?
echo "One orchestrator process exited with code ${status}; stopping remaining processes."
shutdown TERM
wait || true
exit "$status"
