#!/bin/bash
# Quick script to start a Celery worker for DeviceVault

cd "$(dirname "$0")"
source .venv/bin/activate
cd backend

# Start worker with default queue and collection group queues
celery -A celery_app worker \
    -Q storage.fs,storage.git \
    -l info \
    --concurrency=1 \
    --max-tasks-per-child=100 \
    -n storage-worker@%h
    $*
