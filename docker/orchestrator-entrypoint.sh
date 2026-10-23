#!/bin/sh
# DeviceVault orchestrator entrypoint. The first argument selects the role.
set -eu

role="${1:-api}"
[ "$#" -gt 0 ] && shift

case "$role" in
    migrate)
        python manage.py migrate --noinput
        python manage.py create_admin
        # Refuse a second database (e.g. another node's own SQLite file) on the same bus.
        python manage.py claim_installation
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
    scheduler)
        # Runs due backup schedules and expires stuck jobs. Safe to run on
        # every node: only the holder of a Redis lease acts.
        exec python manage.py run_scheduler "$@"
        ;;
    events)
        # Worker registration, heartbeats and job events (queue dv.orchestrator).
        exec celery -A devicevault.celery worker \
            --queues=dv.orchestrator \
            --hostname="events@%h" \
            --concurrency="${DV_EVENTS_CONCURRENCY:-4}" \
            --loglevel="${DV_LOG_LEVEL:-INFO}" \
            "$@"
        ;;
    flower)
        # Behind the web tier's /flower/<slug>/ proxy, DV_FLOWER_URL_PREFIX is flower/<slug>.
        exec celery -A devicevault.celery flower \
            --address=0.0.0.0 --port=5555 \
            ${DV_BROKER_API:+--broker-api="$DV_BROKER_API"} \
            ${DV_FLOWER_URL_PREFIX:+--url_prefix="$DV_FLOWER_URL_PREFIX"} \
            "$@"
        ;;
    manage)
        exec python manage.py "$@"
        ;;
    *)
        exec "$role" "$@"
        ;;
esac
