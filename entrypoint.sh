#!/bin/sh
# CivicFlow backend entrypoint

set -e

if [ "${BOOTSTRAP_ON_START:-false}" = "true" ]; then
    python /app/bootstrap.py
fi

echo "Starting Gunicorn..."
exec gunicorn -c /app/gunicorn.conf.py "wsgi:app"
