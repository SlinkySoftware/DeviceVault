#!/bin/bash

cd "$(dirname "$0")"
source .venv/bin/activate
cd backend
celery -A celery_app flower --broker-api=http://guest:guest@localhost:15672/api/ --port=5555
