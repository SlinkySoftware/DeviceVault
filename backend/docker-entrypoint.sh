#!/bin/bash

# Run Django migrations
python manage.py migrate --run-syncdb --noinput

# Start the main Django application
exec "$@"
