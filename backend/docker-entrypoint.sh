#!/bin/bash

# Run Django migrations
python manage.py migrate --noinput -- run-syncdb

# Start the main Django application
exec "$@"
