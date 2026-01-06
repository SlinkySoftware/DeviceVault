#!/bin/sh

# Replace placeholders with environment variables
sed -i "s|PLACEHOLDER_API_URL|$API_URL|g" /var/www/html/services/api.js

# Execute the main container command (e.g., starting Nginx)
exec "$@"
