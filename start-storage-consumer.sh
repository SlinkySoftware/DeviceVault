#!/bin/bash
# Quick script to start the DeviceVault result consumer

cd "$(dirname "$0")"
source .venv/bin/activate
cd backend

# Start consumer to listen for results on Redis Stream and persist to DB
python manage.py consume_storage_results
