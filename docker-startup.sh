#!/bin/bash
set -e

LOCK_FILE="/tmp/migrations.lock"

echo "Waiting for migration lock..."

# Running alembic upgrade head.
echo "Running migrations..."
if flock -x "$LOCK_FILE" -c "alembic upgrade head"; then
    echo "Migrations check completed successfully."
else
    echo "WARNING: Migrations failed. Check the logs above. Application might fail if tables are missing."
fi


echo "Starting application..."
exec "$@"
