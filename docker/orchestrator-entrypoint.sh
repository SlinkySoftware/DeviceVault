#!/bin/sh
# DeviceVault orchestrator entrypoint. The first argument selects the role.
set -eu

role="${1:-api}"
[ "$#" -gt 0 ] && shift

case "$role" in
    migrate)
        python manage.py migrate --noinput
        python manage.py create_admin
        ;;
    api)
        exec gunicorn devicevault.wsgi:application \
            --bind 0.0.0.0:8000 \
            --workers "${DV_API_WORKERS:-3}" \
            --timeout "${DV_API_TIMEOUT:-90}" \
            --access-logfile - \
            "$@"
        ;;
    api-dev)
        exec python manage.py runserver 0.0.0.0:8000 "$@"
        ;;
    collect-results)
        exec python manage.py consume_device_results "$@"
        ;;
    store-results)
        exec python manage.py consume_storage_results "$@"
        ;;
    events)
        # Worker registration and heartbeats (queue dv.orchestrator).
        exec celery -A devicevault.celery worker \
            --queues=dv.orchestrator \
            --hostname="events@%h" \
            --concurrency="${DV_EVENTS_CONCURRENCY:-2}" \
            --loglevel="${DV_LOG_LEVEL:-INFO}" \
            "$@"
        ;;
    flower)
        exec celery -A devicevault.celery flower \
            --address=0.0.0.0 --port=5555 \
            ${DV_BROKER_API:+--broker-api="$DV_BROKER_API"} \
            "$@"
        ;;
    manage)
        exec python manage.py "$@"
        ;;
    *)
        exec "$role" "$@"
        ;;
esac
