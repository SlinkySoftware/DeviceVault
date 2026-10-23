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
python manage.py migrate --noinput

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
start_process "worker-monitor" python manage.py monitor_worker_registry
start_process "celery-beat" celery -A celery_app beat -l info -s /var/devicevault/logs/orchestrator/celerybeat-schedule

wait -n "${PIDS[@]}"
status=$?
echo "One orchestrator process exited with code ${status}; stopping remaining processes."
shutdown TERM
wait || true
exit "$status"
